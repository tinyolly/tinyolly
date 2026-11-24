HTML = """<!doctype html><meta charset=utf-8><title>TinyOlly SRE</title>
<style>body{font:13px ui-monospace,monospace;margin:0;background:#0f1117;color:#d7dae0}#bar{padding:8px 12px;background:#1a1d27;position:sticky;top:0}
.l{padding:3px 12px;border-bottom:1px solid #1a1d27;cursor:pointer}.WARNING{color:#e5c07b}.ERROR{color:#e06c75}pre{white-space:pre-wrap;color:#9aa;margin:4px 0}
#a{position:sticky;bottom:0;background:#1a1d27;padding:8px;display:flex;gap:6px}#a input{flex:1;background:#0f1117;color:inherit;border:1px solid #333;padding:6px}#r{padding:6px 12px;color:#98c379}</style>
<div id=bar>TinyOlly SRE <span id=s></span></div><div id=f></div><div id=r></div>
<div id=a><input id=q maxlength=400 placeholder="Ask about your telemetry"><button onclick=ask()>Ask</button></div>
<script>let n=0;async function p(){try{const j=await (await fetch('events?after='+n)).json();s.textContent=' | open incidents '+j.status.open_incidents+' | model '+j.status.model+' | runs/h '+j.status.investigations_last_hour+'/'+j.status.max_per_hour;
for(const e of j.events){n=e.n;const d=document.createElement('div');d.className='l '+e.lvl;d.textContent=e.t+' '+e.msg;if(e.detail){d.onclick=()=>{if(d.nextSibling&&d.nextSibling.tagName=='PRE')d.nextSibling.remove();else{const x=document.createElement('pre');x.textContent=e.detail;d.after(x)}}}f.append(d)}
if(j.events.length)scrollTo(0,document.body.scrollHeight)}catch(e){}setTimeout(p,2000)}p();
async function ask(){r.textContent='thinking...';const j=await (await fetch('ask',{method:'POST',body:JSON.stringify({question:q.value})})).json();r.textContent=j.answer||j.error}</script>"""
