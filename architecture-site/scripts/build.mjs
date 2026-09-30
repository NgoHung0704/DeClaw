import {mkdir,readFile,writeFile,copyFile,readdir} from 'node:fs/promises';
import {resolve,dirname,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {nodes,edges} from '../content.js';

const site=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const repo=resolve(site,'..');
const dist=resolve(site,'dist');
await mkdir(dist,{recursive:true});
const commit=execFileSync('git',['-c',`safe.directory=${repo.replaceAll('\\','/')}`,'rev-parse','HEAD'],{cwd:repo,encoding:'utf8'}).trim();
const inventory={};
const ownership={brain:['declaw/brain'],tools:['declaw/tools'],documents:['declaw/documents'],plugins:['declaw/plugin_host','declaw_plugin_sdk','plugins/builtin/doc-intel'],sanitizer:['declaw/sanitizer'],memory:['declaw/memory'],audit:['declaw/audit'],storage:['declaw/db','alembic'],credentials:['declaw/credentials'],cli:['scripts']};
async function walk(dir){let result=[];for(const e of await readdir(resolve(repo,dir),{withFileTypes:true})){if(e.name==='__pycache__')continue;const p=`${dir}/${e.name}`;if(e.isDirectory())result.push(...await walk(p));else if(e.name.endsWith('.py'))result.push(p);}return result.sort();}
for(const [id,dirs] of Object.entries(ownership)){inventory[id]=[];for(const d of dirs)inventory[id].push(...await walk(d));}
inventory.cli.push('declaw/__init__.py','declaw/log.py');
const fileNames=[...new Set([...nodes.flatMap(n=>n.files),...edges.map(e=>e.file),...Object.values(inventory).flat()])];
const files={};
for(const name of fileNames){if(!name.endsWith('.py')||name.includes('..'))throw Error(`Invalid source path ${name}`);files[name]=(await readFile(resolve(repo,name),'utf8')).replaceAll('\r\n','\n');}
for(const name of ['index.html','content.js','app.js','style.css'])await copyFile(resolve(site,name),resolve(dist,name));
await writeFile(resolve(dist,'snapshot.json'),JSON.stringify({commit,files,inventory},null,2)+'\n');
console.log(`Built DeClaw Atlas: ${nodes.length} components, ${edges.length} contracts, ${fileNames.length} source files. Snapshot ${commit.slice(0,7)}.`);
