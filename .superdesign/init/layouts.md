# Shared layouts
Existing React shell and new self-contained vanilla JS explorer shell.
## `docs-site/src/App.tsx`
```
import { useCallback } from 'react';
import { AnimatePresence } from 'motion/react';
import { ui } from './content/load';
import type { Lang } from './content/types';
import { LangProvider, useT } from './i18n/lang';
import { RouterProvider, useNavigate, useRoute } from './router/Router';
import { MapView } from './views/MapView';
import { ComponentsView } from './views/ComponentsView';
import { DetailView } from './views/DetailView';
import { MachineView } from './views/MachineView';
import { DebtView } from './views/DebtView';
import { PhasesView } from './views/PhasesView';

const VIEWS = ['map', 'phases', 'components', 'machine', 'debt'] as const;
type ViewName = (typeof VIEWS)[number];

function CurrentView({ view, id }: { view: string; id?: string }) {
  if (view === 'phases') return <PhasesView />;
  if (view === 'components') return <ComponentsView />;
  if (view === 'component' && id) return <DetailView id={id} />;
  if (view === 'machine') return <MachineView />;
  if (view === 'debt') return <DebtView />;
  return <MapView />;
}

function Shell() {
  const t = useT();
  const route = useRoute();
  const navigate = useNavigate();
  const view = route.segments[0] ?? 'map';
  const lang: Lang = route.query.lang === 'vi' ? 'vi' : 'en';

  const switchLang = (next: Lang) => {
    navigate({ segments: route.segments, query: { ...route.query, lang: next } }, { replace: true });
  };

  return (
    <>
      <a className="skip" href="#main">
        {t(ui.site.skipToContent)}
      </a>
      <header className="masthead">
        <div className="masthead__title">
          <h1>{t(ui.site.title)}</h1>
          <p>{t(ui.site.tagline)}</p>
        </div>
        <div className="masthead__controls">
          <nav aria-label={t(ui.nav.label)}>
            <ul className="nav">
              {VIEWS.map((name: ViewName) => (
                <li key={name}>
                  <button
                    type="button"
                    className="nav__button"
                    aria-current={view === name ? 'page' : undefined}
                    onClick={() => navigate({ segments: [name], query: route.query })}
                  >
                    {t(ui.nav[name])}
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <div className="langswitch" role="group" aria-label={t(ui.nav.languageLabel)}>
            <button
              type="button"
              className="langswitch__button"
              aria-pressed={lang === 'en'}
              onClick={() => switchLang('en')}
            >
              {t(ui.nav.english)}
            </button>
            <button
              type="button"
              className="langswitch__button"
              aria-pressed={lang === 'vi'}
              onClick={() => switchLang('vi')}
            >
              {t(ui.nav.vietnamese)}
            </button>
          </div>
        </div>
      </header>

      <main id="main" data-view={view}>
        <AnimatePresence mode="wait">
          <CurrentView key={view} view={view} id={route.segments[1]} />
        </AnimatePresence>
      </main>
    </>
  );
}

/** Language lives in the hash query so a shared link keeps its language. */
function LangBridge() {
  const route = useRoute();
  const navigate = useNavigate();
  const lang: Lang = route.query.lang === 'vi' ? 'vi' : 'en';
  const setLang = useCallback(
    (next: Lang) =>
      navigate(
        { segments: route.segments, query: { ...route.query, lang: next } },
        { replace: true },
      ),
    [navigate, route.segments, route.query],
  );
  return (
    <LangProvider lang={lang} setLang={setLang}>
      <Shell />
    </LangProvider>
  );
}

export function App() {
  return (
    <RouterProvider>
      <LangBridge />
    </RouterProvider>
  );
}

```

## `architecture-site/app.js`
```
import {ui, nodes, edges, journeys, lessons, L} from './content.js';

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
 map:'M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2V5zm6-2v16m6-14v16',
 flow:'M4 6h11m-4-4 4 4-4 4M20 18H9m4-4-4 4 4 4M4 14v4m16-12v4',
 grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
 book:'M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1zm0 0v15',
 arrow:'M5 12h14m-5-5 5 5-5 5', chevron:'m9 5 7 7-7 7',
 close:'m6 6 12 12M6 18 18 6', search:'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
 cli:'m4 6 6 6-6 6m9 0h7', brain:'M9 3v3H6v4H3v4h3v4h3v3m6-18v3h3v4h3v4h-3v4h-3v3M9 10h6v4H9z',
 tools:'m14 6 4 4M3 21l8-8m1-9a6 6 0 0 0-7 8l7-7a6 6 0 0 0 8 7l-7 7a6 6 0 0 0 7-8',
 documents:'M6 3h9l4 4v14H6V3zm9 0v5h4M9 12h7m-7 4h7',
 plugins:'M9 3h6v5h5v6h-5v7H9v-7H3V8h6V3z',
 sanitizer:'m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6l8-4zm-4 10 3 3 5-6',
 memory:'M5 5h14v14H5zM9 9h6v6H9zM8 1v4m8-4v4M8 19v4m8-4v4M1 8h4m-4 8h4m14-8h4m-4 8h4',
 audit:'M4 3h16v18H4zM8 8h8m-8 4h8m-8 4h5',
 ollama:'M7 3h10l4 9-4 9H7l-4-9 4-9zm1 9h8m-4-4v8',
 storage:'M3 6c0-4 18-4 18 0s-18 4-18 0zm0 0v12c0 4 18 4 18 0V6M3 12c0 4 18 4 18 0',
 workspace:'M3 6h7l2 3h9v11H3V6z', credentials:'M8 10V7a4 4 0 0 1 8 0v3M5 10h14v11H5zM12 14v3',
 sun:'M12 3V1m0 22v-2M3 12H1m22 0h-2M5 5 3 3m18 18-2-2M5 19l-2 2M21 3l-2 2M17 12a5 5 0 1 1-10 0 5 5 0 0 1 10 0',
 play:'m8 4 12 8-12 8V4z', pause:'M8 4v16M16 4v16', link:'m9 15 6-6M8 17l-2 2a4 4 0 0 1-5-5l5-5a4 4 0 0 1 6 0m0 6a4 4 0 0 0 6 0l5-5a4 4 0 0 0-5-5l-2 2',
 plus:'M12 5v14M5 12h14', minus:'M5 12h14', fit:'M3 9V3h6m6 0h6v6M3 15v6h6m6 0h6v-6',
 code:'m8 6-6 6 6 6m8-12 6 6-6 6m-3-15-2 18', check:'m5 12 4 4L19 6',
};
const icon = (id, cls='') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[id] || paths.grid}"/></svg>`;
let state = {lang:'en',view:'overview',level:'components',journey:'chat',step:0,selected:null,tab:'details',file:null,zoom:1,search:'',playing:false};
let snapshot = {commit:'',files:{},inventory:{}};
let timer;
let returnFocus;
const t = (v) => typeof v === 'string' ? v : (v?.[state.lang] ?? '');
const tr = (key) => esc(t(ui[key]));
const nById = (id) => nodes.find(n=>n.id===id);
const eById = (id) => edges.find(e=>e.id===id);
const currentJourney = () => journeys.find(j=>j.id===state.journey) || journeys[0];
const btn = (action, label, glyph, cls='', extra='') => `<button type="button" class="${cls}" data-action="${action}" ${extra}>${glyph?icon(glyph):''}<span>${esc(label)}</span></button>`;
function readRoute(){
 const q = new URLSearchParams(location.hash.slice(1));
 state.lang=['en','fr','vi'].includes(q.get('lang'))?q.get('lang'):'en';
 state.view=['overview','flows','directory','guide'].includes(q.get('view'))?q.get('view'):'overview';
 state.level=q.get('level')==='context'?'context':'components';
 state.journey=journeys.some(j=>j.id===q.get('journey'))?q.get('journey'):'chat';
 state.step=Math.max(0,Math.min(currentJourney().steps.length-1,Number(q.get('step'))||0));
 state.selected=nodes.some(n=>n.id===q.get('node'))?{kind:'node',id:q.get('node')}:edges.some(e=>e.id===q.get('edge'))?{kind:'edge',id:q.get('edge')}:null;
 state.tab='details';state.file=null;
}
function route(push=false){
 const q=new URLSearchParams({view:state.view,lang:state.lang});
 if(state.level==='context')q.set('level','context');
 if(state.view==='flows'){q.set('journey',state.journey);q.set('step',state.step);}
 if(state.selected)q.set(state.selected.kind,state.selected.id);
 history[push?'pushState':'replaceState'](null,'','#'+q);render();
}
function stop(){clearInterval(timer);state.playing=false;}
function play(){
 if(state.playing){stop();render();return;}
 if(state.step===currentJourney().steps.length-1)state.step=0;
 state.playing=true;route();
 timer=setInterval(()=>{
  if(state.selected || document.hidden)return;
  if(state.step>=currentJourney().steps.length-1){stop();render();return;}
  state.step++;route();
 },4200);
}
function open(kind,id){returnFocus=document.activeElement?.dataset.focus;state.selected={kind,id};state.tab='details';state.file=null;route(true);}
function close(){state.selected=null;state.file=null;route();if(returnFocus)document.querySelector(`[data-focus="${CSS.escape(returnFocus)}"]`)?.focus();}
function nav(){return `<aside class="sidebar"><a class="wordmark" href="#view=overview&lang=${state.lang}" aria-label="DeClaw Atlas"><span class="brand-symbol">${icon('brain')}</span><span>DeClaw<span class="brand-sub">ATLAS</span></span></a><div class="workspace-label"><span class="status-dot"></span> DeClaw <span class="version">v0.1</span></div><p class="nav-caption">${tr('explore')}</p><nav>${[['overview','map'],['flows','flow'],['directory','grid'],['guide','book']].map(([key,g])=>btn('view',t(ui[key]),g,`nav-link ${state.view===key?'active':''}`,`data-value="${key}" ${state.view===key?'aria-current="page"':''}`)).join('')}</nav><div class="sidebar-bottom"><div class="local-note">${icon('sanitizer')}<div><strong>${tr('local')}</strong><span>Python · Ollama · SQLite</span></div></div><div class="sidebar-meta">${tr('snapshot')}<code>${esc(snapshot.commit?.slice(0,7) || '—')}</code></div></div></aside>`;}
function header(){return `<header class="topbar"><div class="breadcrumb"><span>DeClaw</span>${icon('chevron')}<strong>${tr(state.view)}</strong></div><div class="header-actions">${btn('theme',t(ui.theme),'sun','icon-button')}<label class="language"><span aria-hidden="true">◎</span><select id="language" aria-label="${tr('language')}">${[['en','English'],['fr','Français'],['vi','Tiếng Việt']].map(([v,n])=>`<option value="${v}" ${state.lang===v?'selected':''}>${n}</option>`).join('')}</select></label>${btn('copy',t(ui.copy),'link','icon-button')}</div></header>`;}
function hero(){return `<section class="hero"><div><p class="eyebrow"><span class="status-dot"></span>${tr('project')}</p><h1>${tr('heading').replace('\n','<br>')}</h1><p class="hero-description">${tr('intro')}</p></div><div class="hero-right">${btn('tour',t(ui.tour),'arrow','primary')}<span class="verified">${icon('check')}${tr('sourceBacked')}</span></div></section>`;}

// Selected overview edges keep the diagram readable; all contracts remain in the connection list.
const overviewEdges=['request','inference','invoke','screen','parse','vectors','recall','key'];
function curve(a,b,i=0){
 const w=218,h=94;
 if(a.x===b.x){const down=b.y>a.y;return `M${a.x+w/2},${a.y+(down?h:0)} L${b.x+w/2},${b.y+(down?0:h)}`;}
 if(Math.abs(a.x-b.x)>300 && Math.abs(a.y-b.y)<10){const lift=Math.min(a.y,b.y)-28-i*5;return `M${a.x+w/2},${a.y} C${a.x+w/2},${lift} ${a.x+w/2},${lift} ${a.x+w/2+30},${lift} L${b.x+w/2-30},${lift} Q${b.x+w/2},${lift} ${b.x+w/2},${b.y}`;}
 const right=b.x>a.x;const sx=a.x+(right?w:0),ex=b.x+(right?0:w),sy=a.y+h/2,ey=b.y+h/2;
 return `M${sx},${sy} C${(sx+ex)/2},${sy} ${(sx+ex)/2},${ey} ${ex},${ey}`;
}
function contextNodes(){return [
 {...nById('cli'),x:25,y:190},
 {id:'core',name:ui.coreTitle,subtitle:ui.coreDesc,tech:'Python · LangGraph',group:'core',x:330,y:190},
 {...nById('ollama'),x:760,y:55},
 {...nById('plugins'),x:760,y:200},
 {...nById('storage'),x:760,y:345},
 {...nById('workspace'),x:330,y:405},
 ];}
function graph(flow=false){
 const context=!flow&&state.level==='context';const list=context?contextNodes():nodes;
 const activeEdge=flow?eById(currentJourney().steps[state.step].edge):null;
 const visualEdges=context?[
 {id:'request',from:'cli',to:'core'}, {id:'inference',from:'core',to:'ollama'}, {id:'parse',from:'core',to:'plugins'}, {id:'vectors',from:'core',to:'storage'}, {id:'file',from:'core',to:'workspace'}
 ]:flow?[activeEdge]:overviewEdges.map(eById);
 const visited=flow?new Set(currentJourney().steps.flatMap(s=>{const e=eById(s.edge);return [e.from,e.to]})):null;
 return `<div class="map-surface ${flow?'flow-map':''}"><div class="map-scroll"><div class="graph-scaler" style="width:${1060*state.zoom}px;height:${625*state.zoom}px"><div class="graph-world" style="transform:scale(${state.zoom})"><div class="machine-boundary">${icon('sanitizer')}${tr('boundary')}</div>${!context?`<div class="process-boundary"><span>${tr('process')}</span></div>`:''}<svg class="wires" width="1060" height="625" viewBox="0 0 1060 625" aria-hidden="true"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${flow?'#138769':'#8ba49b'}"/></marker></defs>${visualEdges.map((e,i)=>{const a=list.find(n=>n.id===e.from),b=list.find(n=>n.id===e.to);return a&&b?`<path class="wire ${flow?'live':''}" d="${curve(a,b,i)}" marker-end="url(#arrow)"/>`:''}).join('')}</svg>${list.map(n=>`<button data-action="node" data-value="${n.id}" data-focus="node-${n.id}" class="node ${n.group} ${activeEdge&&(n.id===activeEdge.from||n.id===activeEdge.to)?'illuminated':''} ${visited&&!visited.has(n.id)?'dimmed':''}" style="left:${n.x}px;top:${n.y}px" aria-label="${tr('open')}: ${esc(t(n.name))}"><span class="node-top"><span class="node-icon">${icon(n.id==='core'?'brain':n.id)}</span><span class="node-title">${esc(t(n.name))}</span>${icon('chevron','node-chevron')}</span><span class="node-subtitle">${esc(t(n.subtitle))}</span><span class="node-tech"><i></i>${esc(n.tech)}</span></button>`).join('')}${context?`<div class="context-note">${tr('howBody')}</div>`:`<div class="column-label" style="left:30px">01 / ${tr('interface')}</div><div class="column-label" style="left:290px">02 / ${tr('logic')}</div><div class="column-label" style="left:550px">03 / ${tr('safety')}</div><div class="column-label" style="left:810px">04 / ${tr('infrastructure')}</div>`}</div></div></div><div class="map-bottom"><span>${icon('map')}${tr('legend')}</span><div class="zoom">${btn('zoom-out',t(ui.zoomOut),'minus','icon-button')}<span>${Math.round(state.zoom*100)}%</span>${btn('zoom-in',t(ui.zoomIn),'plus','icon-button')}${btn('fit',t(ui.fit),'fit','icon-button')}</div></div></div>`;
}
function connectionList(list=edges){return `<div class="connection-list">${list.map(e=>`<button class="connection-row" data-action="edge" data-value="${e.id}" data-focus="edge-${e.id}"><span>${esc(t(nById(e.from).name))} ${icon('arrow')} ${esc(t(nById(e.to).name))}</span><strong>${esc(t(e.label))}</strong>${icon('chevron')}</button>`).join('')}</div>`;}
function overview(){return `${hero()}<section class="map-card"><div class="section-bar"><div><h2>${tr('map')}</h2><p>${tr('mapHint')}</p></div><div class="segmented" role="group" aria-label="${tr('map')}">${['context','components'].map(v=>btn('level',t(ui[v]),null,state.level===v?'selected':'',`data-value="${v}" aria-pressed="${state.level===v}"`)).join('')}</div></div>${graph()}<div class="map-footer"><span class="badge"><i></i>${nodes.length} ${tr('components')} · ${tr('built')}</span><span class="planned-note"><span class="planned-dot"></span>${tr('plannedNote')}</span></div></section><div class="below-grid"><div class="explain-card">${icon('grid')}<div><h3>${tr('how')}</h3><p>${tr('howBody')}</p></div></div><button class="journey-promo" data-action="tour"><span class="promo-icon">${icon('flow')}</span><span><strong>${tr('tour')}</strong><small>${esc(t(journeys[0].title))} · ${esc(t(journeys[3].title))}</small></span>${icon('arrow')}</button></div><details class="contracts"><summary>${tr('connections')} <span>${edges.length}</span></summary>${connectionList()}</details>`;}
function flowView(){const j=currentJourney(),s=j.steps[state.step],e=eById(s.edge);return `<section class="page-heading"><p class="eyebrow">${tr('flows')}</p><h1>${tr('flowHeading')}</h1><p>${tr('flowIntro')}</p></section><div class="journey-tabs" role="group" aria-label="${tr('flows')}">${journeys.map((j,i)=>btn('journey',t(j.title),null,state.journey===j.id?'selected':'',`data-value="${j.id}" aria-pressed="${state.journey===j.id}"`)).join('')}</div><section class="map-card"><div class="section-bar"><div><h2>${esc(t(j.title))}</h2><code>${esc(j.command)}</code></div><div class="flow-controls">${btn('reset',t(ui.reset),'fit','icon-button')}${btn('play',t(ui[state.playing?'pause':'play']),state.playing?'pause':'play','primary')}</div></div><div class="stepper">${j.steps.map((s,i)=>`<button data-action="step" data-value="${i}" class="step ${i===state.step?'active':i<state.step?'complete':''}" aria-current="${i===state.step?'step':'false'}"><span>${i<state.step?icon('check'):String(i+1).padStart(2,'0')}</span><strong>${esc(t(s.title))}</strong></button>`).join('')}</div>${graph(true)}<div class="flow-explanation" aria-live="polite"><div><span class="eyebrow">${tr('step')} ${state.step+1} / ${j.steps.length}</span><h3>${esc(t(s.title))}</h3><p>${esc(t(s.text))}</p></div><div class="step-contract"><span>${esc(t(e.transport))}</span><code>${esc(t(e.payload))}</code>${btn('edge',t(ui.connections),'arrow','text-button',`data-value="${e.id}"`)}</div></div><div class="flow-pagination">${btn('previous',t(ui.previous),null,'secondary',state.step===0?'disabled':'')}${btn('next',t(ui.next),'arrow','secondary',state.step===j.steps.length-1?'disabled':'')}</div></section>`;}
function filesFor(n){return [...new Set([...n.files,...(snapshot.inventory[n.id]||[])])];}
function directory(){const query=state.search.toLocaleLowerCase();const matches=nodes.filter(n=>[t(n.name),t(n.description),...filesFor(n)].join(' ').toLocaleLowerCase().includes(query));return `<section class="page-heading"><p class="eyebrow">${tr('components')}</p><h1>${tr('directory')}</h1><p>${tr('directoryIntro')}</p></section><div class="directory-toolbar"><span>${matches.length} / ${nodes.length} ${tr('components')}</span><label class="search-field">${icon('search')}<input id="search" type="search" autocomplete="off" placeholder="${tr('search')}" aria-label="${tr('search')}" value="${esc(state.search)}"></label></div><div class="component-grid">${matches.map(n=>`<button class="component-card ${n.group}" data-action="node" data-value="${n.id}" data-focus="directory-${n.id}"><span class="node-icon">${icon(n.id)}</span><span class="badge">${filesFor(n).length} ${tr('modules')}</span><h2>${esc(t(n.name))}</h2><p>${esc(t(n.subtitle))}</p><code>${esc(n.tech)}</code><span class="card-link">${tr('open')}${icon('arrow')}</span></button>`).join('')||`<p class="empty">${tr('noResults')}</p>`}</div>`;}
function guide(){return `<section class="page-heading"><p class="eyebrow">${tr('guide')}</p><h1>${tr('guideHeading')}</h1><p>${tr('guideIntro')}</p></section><div class="lesson-grid">${lessons.map((l,i)=>`<button class="lesson" data-action="lesson" data-value="${i}"><span class="lesson-number">0${i+1}</span><h2>${esc(t(l.title))}</h2><p>${esc(t(l.text))}</p>${icon('arrow')}</button>`).join('')}</div><div class="guide-note">${icon('sanitizer')}<div><h3>${tr('how')}</h3><p>${tr('howBody')}</p><p>${tr('plannedNote')}</p></div></div>`;}
function nodeDetail(n){
 const tabs=['details','internals','source','connections'];
 let body='';
 if(state.tab==='details')body=`<p class="eyebrow">${tr('responsibility')}</p><p class="detail-description">${esc(t(n.description))}</p><div class="io-grid"><div><span>${tr('input')}</span><p>${esc(t(n.input))}</p></div><div><span>${tr('output')}</span><p>${esc(t(n.output))}</p></div></div><div class="rule">${icon('sanitizer')}<div><h3>${tr('invariant')}</h3><p>${esc(t(n.rule))}</p></div></div>${btn('tab',t(ui.internals),'arrow','primary',`data-value="internals"`)}`;
 if(state.tab==='internals')body=`<h3>${tr('internals')}</h3><div class="internal-flow ${n.id==='tools'||n.id==='sanitizer'?'branching':''}">${n.parts.map((p,i)=>`<div class="internal-step"><span>${String(i+1).padStart(2,'0')}</span><strong>${esc(t(p))}</strong></div>`).join('')}</div><div class="rule"><p>${esc(t(n.rule))}</p></div><h3>${tr('source')}</h3>${filesFor(n).map(f=>btn('file',f,'code','file-row',`data-value="${esc(f)}"`)).join('')}`;
 if(state.tab==='source'){
 const files=filesFor(n);const file=files.includes(state.file)?state.file:files[0];
 body=`<p class="muted">${tr('fileHint')}</p><label class="file-select"><select id="file-select" aria-label="${tr('source')}">${files.map(f=>`<option value="${esc(f)}" ${f===file?'selected':''}>${esc(f)}</option>`).join('')}</select></label><div class="source-meta"><code>${esc(file)}</code><span>${esc(snapshot.commit?.slice(0,7))}</span></div><pre class="source-code" tabindex="0"><code>${snapshot.files[file]!==undefined?snapshot.files[file].split('\n').map((line,i)=>`<span class="code-line"><span class="line-number" aria-hidden="true">${i+1}</span>${esc(line)||' '}</span>`).join(''):tr('sourceUnavailable')}</code></pre>`;
 }
 if(state.tab==='connections')body=connectionList(edges.filter(e=>e.from===n.id||e.to===n.id));
 return `<div class="detail-identity"><span class="node-icon ${n.group}">${icon(n.id)}</span><div><span class="eyebrow">${tr('components')}</span><h2 id="detail-title">${esc(t(n.name))}</h2><code>${esc(n.tech)}</code></div></div><div class="detail-tabs" role="tablist">${tabs.map(k=>btn('tab',t(ui[k]),null,state.tab===k?'active':'',`data-value="${k}" role="tab" id="tab-${k}" aria-controls="detail-body" aria-selected="${state.tab===k}" tabindex="${state.tab===k?0:-1}"`)).join('')}</div><div class="detail-body" id="detail-body" role="tabpanel" aria-labelledby="tab-${state.tab}">${body}</div>`;
}
function edgeDetail(e){return `<div class="detail-identity"><span class="node-icon">${icon('flow')}</span><div><span class="eyebrow">${tr('connections')}</span><h2 id="detail-title">${esc(t(e.label))}</h2></div></div><div class="detail-body"><div class="edge-endpoints">${btn('node',t(nById(e.from).name),e.from,'endpoint',`data-value="${e.from}"`)}${icon('arrow')}${btn('node',t(nById(e.to).name),e.to,'endpoint',`data-value="${e.to}"`)}</div><dl class="contract-fields"><dt>${tr('transport')}</dt><dd>${esc(t(e.transport))}</dd><dt>${tr('payload')}</dt><dd><code>${esc(t(e.payload))}</code></dd><dt>${tr('failure')}</dt><dd>${esc(t(e.failure))}</dd><dt>${tr('source')}</dt><dd>${btn('edge-file',e.file,'code','file-row',`data-value="${e.id}"`)}</dd></dl></div>`;}
function dialog(){if(!state.selected)return '';const sel=state.selected;return `<dialog id="details-dialog" aria-labelledby="detail-title"><div class="dialog-top"><span>${tr('atlas')}</span>${btn('close',t(ui.close),'close','icon-button','autofocus')}</div>${sel.kind==='node'?nodeDetail(nById(sel.id)):edgeDetail(eById(sel.id))}</dialog>`;}
function render(){
 const active=document.activeElement;const activeId=active?.id;const action=active?.dataset?.action;const value=active?.dataset?.value;
 const selection=active?.tagName==='INPUT'?active.selectionStart:null;
 const scroll=$('.map-scroll')?.scrollLeft||0;const detailScroll=$('.detail-body')?.scrollTop||0;
 document.documentElement.lang=state.lang;document.title=`DeClaw Atlas · ${t(ui[state.view])}`;
 $('#app').innerHTML=`<a class="skip" href="#main">${tr('skip')}</a>${nav()}<div class="shell">${header()}<main id="main">${state.view==='overview'?overview():state.view==='flows'?flowView():state.view==='directory'?directory():guide()}<footer><span>DeClaw Atlas</span><span>${tr('snapshot')} · ${esc(snapshot.commit?.slice(0,7)||'—')} · EN / FR / VI</span></footer></main></div>${dialog()}<div id="toast" role="status"></div>`;
 if(state.selected){const d=$('#details-dialog');d.showModal();d.addEventListener('cancel',e=>{e.preventDefault();close()});d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close();}});}
 if(activeId && document.getElementById(activeId)){const el=document.getElementById(activeId);el.focus({preventScroll:true});if(selection!==null && el.setSelectionRange)el.setSelectionRange(selection,selection);}
 else if(action){document.querySelector(`[data-action="${CSS.escape(action)}"]${value!==undefined?`[data-value="${CSS.escape(value)}"]`:''}`)?.focus({preventScroll:true});}
 if($('.map-scroll'))$('.map-scroll').scrollLeft=scroll;
 if($('.detail-body'))$('.detail-body').scrollTop=detailScroll;
}
document.addEventListener('click',async event=>{
 const target=event.target.closest('[data-action]');if(!target)return;
 const {action,value}=target.dataset;
 if(action==='view'){stop();state.view=value;state.selected=null;state.search='';route(true);window.scrollTo(0,0);}
 else if(action==='tour'){stop();state.view='flows';state.level='components';state.step=0;route(true);window.scrollTo(0,0);}
 else if(action==='level'){state.level=value;route();}
 else if(action==='node'){if(value==='core'){state.level='components';route();}else open('node',value);}
 else if(action==='edge')open('edge',value);
 else if(action==='close')close();
 else if(action==='tab'){state.tab=value;render();}
 else if(action==='file'){state.tab='source';state.file=value;render();}
 else if(action==='edge-file'){const e=eById(value);const owner=nodes.find(n=>filesFor(n).includes(e.file));if(owner){state.selected={kind:'node',id:owner.id};state.tab='source';state.file=e.file;route();}}
 else if(action==='journey'){stop();state.journey=value;state.step=0;route();}
 else if(action==='step'){stop();state.step=Number(value);route();}
 else if(action==='play')play();
 else if(action==='next'||action==='previous'){stop();state.step=Math.max(0,Math.min(currentJourney().steps.length-1,state.step+(action==='next'?1:-1)));route();}
 else if(action==='reset'){stop();state.step=0;route();}
 else if(action==='zoom-in'||action==='zoom-out'){state.zoom=Math.max(.5,Math.min(1.6,state.zoom+(action==='zoom-in'?.1:-.1)));render();}
 else if(action==='fit'){state.zoom=Math.min(1,Math.max(.5,($('.map-scroll')?.clientWidth||1060)/1060));render();}
 else if(action==='theme'){const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;try{localStorage.setItem('declaw-atlas-theme',next)}catch{}}
 else if(action==='copy'){try{await navigator.clipboard.writeText(location.href);$('#toast').textContent=t(ui.copied)}catch{$('#toast').textContent=t(ui.copyFailed)}$('#toast').classList.add('visible');setTimeout(()=>$('#toast')?.classList.remove('visible'),3000);}
 else if(action==='lesson'){const l=lessons[Number(value)];if(l.node)open('node',l.node);else{stop();state.view=l.view;state.level=l.level||'components';route(true);window.scrollTo(0,0);}}
});
document.addEventListener('change',e=>{if(e.target.id==='language'){state.lang=e.target.value;route()}if(e.target.id==='file-select'){state.file=e.target.value;render()}});
document.addEventListener('input',e=>{if(e.target.id==='search'){state.search=e.target.value;render()}});
document.addEventListener('keydown',e=>{if(e.target.getAttribute('role')==='tab' && ['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){e.preventDefault();const tabs=['details','internals','source','connections'];const i=tabs.indexOf(state.tab);state.tab=tabs[e.key==='Home'?0:e.key==='End'?3:(i+(e.key==='ArrowRight'?1:3))%4];render();$(`#tab-${state.tab}`).focus();}});
window.addEventListener('popstate',()=>{stop();readRoute();render()});
window.addEventListener('hashchange',()=>{stop();readRoute();render()});
try{document.documentElement.dataset.theme=localStorage.getItem('declaw-atlas-theme')||'light'}catch{}
readRoute();render();
fetch('./snapshot.json').then(r=>{if(!r.ok)throw Error('Snapshot');return r.json()}).then(data=>{snapshot=data;render()}).catch(()=>{$('#toast').textContent=t(ui.sourceUnavailable);$('#toast').classList.add('visible')});

```