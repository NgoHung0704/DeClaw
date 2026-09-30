import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {ui,nodes,edges,journeys,lessons} from '../content.js';

test('Every translated record contains English, French and Vietnamese',()=>{
 function visit(o,path){if(!o||typeof o!=='object')return;if('en' in o){for(const lang of ['en','fr','vi'])assert.ok(typeof o[lang]==='string'&&o[lang].trim(),`${path}.${lang}`);}else for(const [k,v] of Object.entries(o))visit(v,`${path}.${k}`);}
 visit({ui,nodes,edges,journeys,lessons},'content');
});
test('Nodes, directed contracts and journey steps resolve without duplicate IDs',()=>{
 for(const list of [nodes,edges,journeys])assert.equal(new Set(list.map(n=>n.id)).size,list.length);
 for(const e of edges){assert.ok(nodes.some(n=>n.id===e.from),e.id);assert.ok(nodes.some(n=>n.id===e.to),e.id);assert.ok(e.payload&&e.transport&&e.failure&&e.file);}
 for(const j of journeys){assert.ok(j.steps.length>=3);for(const s of j.steps)assert.ok(edges.some(e=>e.id===s.edge),`${j.id}:${s.edge}`);}
});
test('Every cited implementation file exists and is Python source',async()=>{
 for(const file of new Set([...nodes.flatMap(n=>n.files),...edges.map(e=>e.file)])){assert.ok(file.endsWith('.py'));await readFile(new URL(`../../${file}`,import.meta.url));}
});
test('Safety-critical teaching paths preserve actual branching',()=>{
 const read=journeys.find(j=>j.id==='read').steps.map(s=>s.edge);
 const write=journeys.find(j=>j.id==='write').steps.map(s=>s.edge);
 const index=journeys.find(j=>j.id==='index').steps.map(s=>s.edge);
 const search=journeys.find(j=>j.id==='search').steps.map(s=>s.edge);
 assert.ok(read.indexOf('file')<read.indexOf('screen'));
 assert.ok(read.includes('classify'));
 assert.ok(!write.includes('screen')&&!write.includes('classify'));
 assert.ok(!index.includes('retrieval-screen'));
 assert.ok(search.indexOf('vectors')<search.indexOf('retrieval-screen'));
});
test('Graph cards do not overlap and stay inside the canvas',()=>{
 for(const n of nodes){assert.ok(n.x>=0&&n.x+218<=1060);assert.ok(n.y>=0&&n.y+94<=625);for(const m of nodes){if(n===m)continue;assert.ok(n.x+218<=m.x||m.x+218<=n.x||n.y+94<=m.y||m.y+94<=n.y,`${n.id} overlaps ${m.id}`);}}
});
