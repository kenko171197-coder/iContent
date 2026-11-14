import{ct as e}from"./app-shell-DOBavobO.js";import{A_ as t,B_ as n,C_ as r,D_ as i,E_ as a,F_ as o,H_ as s,L_ as c,M_ as l,N_ as u,P_ as d,R_ as f,S_ as p,T_ as m,U_ as h,V_ as g,W_ as _,j_ as v,w_ as y}from"./feature-editing-core-tCaXefN0.js";var b=e(`WorkspaceV2Migrator`),x=`filmstrips`,S=`waveform-bin`,C=`preview-audio`,w=`proxies`,T=`thumbnail.meta.json`,E=`thumbnail.jpg`;async function D(e){let t=performance.now(),i={ran:!1,fromVersion:null,toVersion:`2.0`,filmstripMediaMoved:0,waveformBinMoved:0,previewAudioMoved:0,proxiesMoved:0,thumbnailMetaRemoved:0,projectThumbnailsFixed:0,errors:[],durationMs:0},a=await n(e,[r]);if(!a||(i.fromVersion=a.schemaVersion,a.schemaVersion===`2.0`))return i.durationMs=performance.now()-t,i;i.ran=!0,b.info(`Migrating workspace ${a.schemaVersion} → 2.0`);let o=await O(e);try{i.filmstripMediaMoved=await k(e,i.errors)}catch(e){i.errors.push(`filmstrips: ${L(e)}`)}try{i.waveformBinMoved=await A(e,i.errors)}catch(e){i.errors.push(`waveform-bin: ${L(e)}`)}try{i.previewAudioMoved=await j(e,i.errors)}catch(e){i.errors.push(`preview-audio: ${L(e)}`)}try{i.proxiesMoved=await M(e,i.errors)}catch(e){i.errors.push(`proxies: ${L(e)}`)}try{i.thumbnailMetaRemoved=await N(e,i.errors)}catch(e){i.errors.push(`thumbnail-meta: ${L(e)}`)}try{i.projectThumbnailsFixed=await P(e,o,i.errors)}catch(e){i.errors.push(`project-thumbnails: ${L(e)}`)}if(i.errors.length===0){let t={...a,schemaVersion:`2.0`};await h(e,[r],t),b.info(`Workspace migrated to v2`,i)}else b.warn(`Workspace migration completed with errors; marker left at v1 for retry`,{errorCount:i.errors.length});return i.durationMs=performance.now()-t,i}async function O(e){let t=await c(e,[m]),n=new Set;for(let e of t)e.kind===`directory`&&n.add(e.name);return n}async function k(e,t){let n=await c(e,[x]),r=0;for(let a of n){if(a.kind!==`directory`)continue;let n=a.name;try{await _(`migrate-v2:filmstrip:${n}`,async()=>{let t=await c(e,[x,n]);for(let r of t){if(r.kind!==`file`)continue;let t=await f(e,[x,n,r.name]);t&&await s(e,[...i(n),r.name],t)}await g(e,[x,n],{recursive:!0})}),r++}catch(e){t.push(`filmstrip ${n}: ${L(e)}`)}}return r>0&&await F(e,x),r}async function A(e,t){let n=await c(e,[S]),r=0;for(let i of n){if(i.kind!==`file`||!i.name.endsWith(`.bin`))continue;let n=i.name.slice(0,-4);try{await _(`migrate-v2:waveform-bin:${n}`,async()=>{let t=await f(e,[S,i.name]);t&&(await s(e,d(n),t),await g(e,[S,i.name]))}),r++}catch(e){t.push(`waveform-bin ${n}: ${L(e)}`)}}return r>0&&await F(e,S),r}async function j(e,t){let n=await c(e,[C]),r=0;for(let i of n){if(i.kind!==`directory`)continue;let n=await c(e,[C,i.name]);for(let a of n){if(a.kind!==`directory`)continue;let n=await c(e,[C,i.name,a.name]);for(let o of n){if(o.kind!==`file`||!o.name.endsWith(`.wav`))continue;let n=o.name.slice(0,-4);try{await _(`migrate-v2:preview-audio:${n}`,async()=>{let t=await f(e,[C,i.name,a.name,o.name]);t&&(await s(e,v(n),t),await g(e,[C,i.name,a.name,o.name]))}),r++}catch(e){t.push(`preview-audio ${n}: ${L(e)}`)}}await I(e,[C,i.name,a.name])}await I(e,[C,i.name])}return r>0&&await F(e,C),r}async function M(e,t){let n=await c(e,[w]),r=0;for(let i of n){if(i.kind!==`directory`)continue;let n=i.name;try{await _(`migrate-v2:proxy:${n}`,async()=>{let t=await c(e,[w,n]);for(let r of t){if(r.kind!==`file`)continue;let t=await f(e,[w,n,r.name]);t&&await s(e,[...u(),n,r.name],t)}await g(e,[w,n],{recursive:!0})}),r++}catch(e){t.push(`proxy ${n}: ${L(e)}`)}}return r>0&&await F(e,w),r}async function N(e,n){let r=await c(e,[y]),i=0;for(let a of r){if(a.kind!==`directory`)continue;let r=a.name,s=[...t(r),T];try{if(!await o(e,s))continue;await g(e,s),i++}catch(e){n.push(`thumbnail.meta ${r}: ${L(e)}`)}}return i}async function P(e,n,r){let i=await c(e,[y]),a=0;for(let o of i){if(o.kind!==`directory`||!n.has(o.name))continue;let i=o.name;try{let n=await c(e,t(i));if(n.some(e=>e.kind===`file`&&e.name===`metadata.json`))continue;let r=await f(e,[...t(i),E]);if(!r||(await s(e,l(i),r),n.some(e=>e.kind!==`file`||e.name!==E)))continue;await g(e,t(i),{recursive:!0}),a++}catch(e){r.push(`project-thumbnail ${i}: ${L(e)}`)}}return a}async function F(e,t){await I(e,[t])}async function I(e,t){if(!((await c(e,t)).length>0))try{await g(e,t)}catch(e){b.debug(`removeDirIfEmpty skipped`,{segments:t,error:e})}}function L(e){return e instanceof Error?e.message:String(e)}var R=`# FreeCut Workspace

This folder is your FreeCut project workspace - the app's source of truth
for everything: projects, media metadata, thumbnails, waveforms, caches.

Everything here is **plain files** you can \`cat\`, \`grep\`, and diff with
normal tools. AI coding agents can read them directly without a browser.

## Layout

\`\`\`
./
|-- README.md                  <- this file
|-- .freecut-workspace.json    <- marker + schema version
|-- index.json                 <- fast project list
|-- projects/
|   \`-- <projectId>/
|       |-- project.json       <- timeline, settings, keyframes, markers, transitions
|       |-- thumbnail.jpg
|       \`-- media-links.json   <- which media this project uses
|-- media/
|   \`-- <mediaId>/
|       |-- metadata.json      <- codec, duration, resolution, etc.
|       |-- source.<ext>       <- inline source file
|       |-- source.link.json   <- OR a link descriptor to an external file
|       |-- thumbnail.jpg
|       \`-- cache/
|           |-- filmstrip/     <- timeline frame thumbnails (0.jpg, 1.jpg, ...)
|           |-- waveform/      <- audio peaks (binned binary + multi-res.bin)
|           |-- gif-frames/    <- pre-extracted GIF frames
|           |-- decoded-audio/ <- chunked PCM for preview playback
|           |-- preview-audio.wav  <- conformed WAV for non-browser codecs
|           \`-- ai/            <- transcripts, captions, scene cuts, ...
\`-- content/
    |-- <hash[0:2]>/<hash>/    <- content-addressable source dedup (reserved)
    |   |-- refs.json
    |   \`-- data.<ext>
    \`-- proxies/<proxyKey>/    <- shared proxies (keyed by content fingerprint)
        |-- proxy.mp4
        \`-- meta.json
\`\`\`

## Safe to edit?

Everything except media source bytes is safe to inspect. Editing
\`project.json\` externally works; FreeCut picks up changes on next load.

Binary caches (waveforms, decoded audio, filmstrips) are regeneratable -
delete them and the app will rebuild them on demand.

## Moving the workspace

You can move this folder to a new location - the app just needs you to
re-pick it via the "Reconnect" prompt on next launch.
`,z=e(`WorkspaceBootstrap`);async function B(e,t){let n=0;async function r(e){let t=[];for await(let n of e.values())t.push({name:n.name,kind:n.kind});for(let i of t){if(i.kind===`directory`){try{await r(await e.getDirectoryHandle(i.name,{create:!1}))}catch(e){z.debug(`sweepStrandedTmpFiles: subdir skipped`,{name:i.name,error:e})}continue}if(i.name.endsWith(`.tmp`))try{await e.removeEntry(i.name),n++}catch(e){z.debug(`sweepStrandedTmpFiles: remove failed`,{name:i.name,error:e})}}}for(let n of t)try{await r(await e.getDirectoryHandle(n,{create:!1}))}catch{}return n}var V=/^[hof]-/;async function H(e){let t=await c(e,u()),n=0;for(let r of t){if(r.kind!==`directory`||!V.test(r.name))continue;let t=r.name,i=t.slice(2),a=[...u(),t],l=[...u(),i];try{if(await o(e,l)){await g(e,a,{recursive:!0}),n++;continue}let r=await c(e,a),i=[],u=!0;for(let t of r){if(t.kind!==`file`)continue;let n=await f(e,[...a,t.name]).catch(()=>null);if(!n){u=!1;break}i.push({name:t.name,blob:n})}if(!u){z.warn(`stripProxyKeyPrefixes: aborting ${t} — unreadable file, leaving source intact`);continue}let d=!0,p=[];for(let n of i)try{await s(e,[...l,n.name],n.blob),p.push(n.name)}catch(e){z.warn(`stripProxyKeyPrefixes: write failed for ${t}/${n.name}`,e),d=!1;break}if(!d){for(let t of p)await g(e,[...l,t],{recursive:!1}).catch(()=>void 0);continue}await g(e,a,{recursive:!0}),n++}catch(e){z.warn(`stripProxyKeyPrefixes: failed to rename ${t}`,e)}}return n}async function U(e){if(!await o(e,[`README.md`]))try{await s(e,[a],R)}catch(e){z.warn(`Failed to write README.md`,e)}if(await o(e,[`.freecut-workspace.json`]))try{let t=await D(e);t.ran&&z.info(`Workspace migration finished`,{from:t.fromVersion,to:t.toVersion,filmstrips:t.filmstripMediaMoved,waveforms:t.waveformBinMoved,previewAudio:t.previewAudioMoved,proxies:t.proxiesMoved,thumbnailMetaRemoved:t.thumbnailMetaRemoved,projectThumbnailsFixed:t.projectThumbnailsFixed,errors:t.errors.length,durationMs:Math.round(t.durationMs)})}catch(e){z.warn(`Workspace migration failed`,e)}else{let t={schemaVersion:`2.0`,createdAt:Date.now()};try{await h(e,[r],t)}catch(e){z.warn(`Failed to write workspace marker`,e)}}try{let t=await H(e);t>0&&z.info(`Stripped source-type prefix from ${t} proxy folder(s)`)}catch(e){z.warn(`stripProxyKeyPrefixes failed`,e)}try{let t=await B(e,[m,y,p]);t>0&&z.info(`Swept ${t} stranded .tmp file(s) from prior crash`)}catch(e){z.warn(`sweepStrandedTmpFiles failed`,e)}}export{U as bootstrapWorkspace};
//# sourceMappingURL=bootstrap-C2bWfsOH.js.map