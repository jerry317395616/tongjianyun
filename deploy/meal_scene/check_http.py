"""No-credential route/ES module checks; rejects data exposure to guests."""
import os
import urllib.request
import urllib.error
from urllib.parse import urlparse

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

base=os.environ.get('MEAL_SCENE_TEST_BASE','http://127.0.0.1:17081')
paths={'/tongjianyun-meal-scene':{303}, '/api/method/tongjianyun.meal_scene.get_overview':{401,403},
    '/api/method/tongjianyun.meal_scene.get_stock':{401,403}}
for filename in ['app.js','state.js','scene.js','app.css']:
    paths['/assets/tongjianyun/meal_scene/'+filename]={200}
opener=urllib.request.build_opener(NoRedirect)
for path,expected in paths.items():
    request=urllib.request.Request(base+path,headers={'Host':'child.myyr.top','User-Agent':'Tongjianyun-Meal-Scene-Readonly-Check'})
    try:
        response=opener.open(request,timeout=30);code=response.status
        if path.endswith('.js'):assert 'javascript' in response.headers.get('Content-Type','')
        response.close()
    except urllib.error.HTTPError as e:
        code=e.code
        if path=='/tongjianyun-meal-scene':
            assert urlparse(e.headers.get('Location','')).path=='/login'
            assert 'no-store' in e.headers.get('Cache-Control','')
    assert code in expected,(path,code)
    print(code,path)
print('PASS: private login redirect, guest data rejection and ES modules')
