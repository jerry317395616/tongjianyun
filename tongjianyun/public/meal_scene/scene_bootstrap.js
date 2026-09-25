import {mealContext,MEALS} from './state.js?v=meal-calendar-read-20260926-2';

// One shared request for calendar and chat modules. This is UI capability data,
// never an authorization token; every business request is checked server-side.
let bootstrapPromise=null;
export function getSceneBootstrap(){
  if(!bootstrapPromise)bootstrapPromise=readBootstrap();
  return bootstrapPromise;
}
async function readBootstrap(){
  const initial=mealContext(),params=new URLSearchParams();
  if(initial.day)params.set('day',initial.day);
  if(initial.meal)params.set('meal',initial.meal);
  const group=new URLSearchParams(location.search).get('group');
  if(group)params.set('group',group);
  const response=await fetch('/api/method/tongjianyun.scene_access.get_bootstrap?'+params,{credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json'}});
  const body=await response.json().catch(()=>({}));
  if(!response.ok||body.exc){
    const error=Error(response.status===401||response.status===403?'当前账号暂不能进入此业务场景，请重新登录或联系管理员。':'业务场景初始化失败，请刷新后重试。');
    error.status=response.status;throw error;
  }
  const result=body.message;
  if(result?.version!==1||typeof result.recipe_calendar!=='boolean'||typeof result.chat?.allowed!=='boolean'
    ||!/^\d{4}-\d{2}-\d{2}$/.test(result.day||'')||!MEALS.some(([key])=>key===result.meal)
    ||!result.default_view?.view||!Array.isArray(result.navigation)||result.navigation.length>12)
    throw Error('业务场景配置不完整，请刷新后重试。');
  return result;
}
