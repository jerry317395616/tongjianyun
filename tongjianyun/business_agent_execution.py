"""Compose native execution with the site's durable host-write evidence.

The native process cannot observe transactions running in the task proxy's host
threads. BOTH queue workers and fresh web/reconciliation processes must use this
wrapper. A closed native lease can revoke future host admission, but cannot
clear active transactions, unresolved commits or resource fences.
"""
from tongjianyun.business_agent_tasks import ExecutionObservation
from tongjianyun.business_agent_writes import BusinessWriteLedger, combine_execution


class BusinessExecutionRuntime:
    def __init__(self, native, ledger, *, proposals=None):
        required = ('ready', 'bind', 'start', 'poll', 'stop', 'record_projection',
                    'observe', 'seal_before_start', 'close')
        if (not isinstance(ledger, BusinessWriteLedger)
                or any(not callable(getattr(native, name, None)) for name in required)):
            raise ValueError('Trusted native runtime and durable host ledger required')
        self.native, self.write_ledger = native, ledger
        if proposals is not None and (getattr(proposals, 'site', None) != ledger.site
                or any(not callable(getattr(proposals, name, None)) for name in ('open_task', 'close_task'))):
            raise ValueError('Draft mutations need a same-site durable admission gate')
        self.proposal_repository = proposals

    def ready(self):
        return self.native.ready()

    def bind(self, claim):
        # Register before any native launch or proxy capability exists. A web
        # cancellation tombstone cannot be reopened by a delayed queue worker.
        self.write_ledger.open_task(claim)
        if self.proposal_repository is not None:
            self.proposal_repository.open_task(claim)
        return self.native.bind(claim)

    def start(self, claim, **inputs):
        return self.native.start(claim, **inputs)

    def poll(self, claim):
        return self.native.poll(claim)

    def close_admission(self, claim):
        try:
            return self.write_ledger.close_task(claim.identity, claim.claim_id)
        finally:
            self._close_proposals(claim.identity, claim.claim_id)

    def _close_proposals(self, identity, claim_id):
        if self.proposal_repository is not None:
            # BEGIN IMMEDIATE serializes the permanent gate with real draft
            # transactions in the SAME database. Busy/I/O failure is unknown,
            # never proof of zero outstanding writes in a fresh web process.
            if self.proposal_repository.close_task(identity, claim_id) is not True:
                raise ValueError('Proposal transaction drainage is not verified')

    def stop(self, claim):
        try:
            self.close_admission(claim)
        finally:
            # A host ledger I/O failure must not leave native execution alive.
            result = self.native.stop(claim)
        return result

    def record_projection(self, claim, observation):
        return self.native.record_projection(claim, observation)

    def observe(self, identity, claim_id):
        native = self.native.observe(identity, claim_id)
        if (isinstance(native, ExecutionObservation) and native.claim_id == claim_id
                and native.lease_closed is True
                and native.state in {'exited', 'never_started_and_sealed'}):
            # This is a permanent native lease proof, not a missing PID/timeout.
            # Any host operation already admitted remains durably active until
            # its own connection closes. Late callbacks now fail admission.
            self.write_ledger.close_task(identity, claim_id)
        host = self.write_ledger.observe(identity, claim_id)
        if (isinstance(native, ExecutionObservation) and native.claim_id == claim_id
                and native.state in {'exited', 'never_started_and_sealed'} and host.admission_closed):
            self._close_proposals(identity, claim_id)
        return combine_execution(native, host)

    def seal_before_start(self, identity, claim_id):
        self.write_ledger.close_task(identity, claim_id)
        self._close_proposals(identity, claim_id)
        native = self.native.seal_before_start(identity, claim_id)
        return combine_execution(native, self.write_ledger.observe(identity, claim_id))

    def close(self, claim):
        try:
            self.close_admission(claim)
        finally:
            result = self.native.close(claim)
        return result
