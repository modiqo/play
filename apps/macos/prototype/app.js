// Interaction prototype: fixtures only. No authentication, installs, or API writes.
// Harness labels and commands mirror scripts/lib/play/harnesses.py.
const icons = {
  home:'<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-7h6v7"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
  grid:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  users:'<circle cx="9" cy="7" r="3"/><path d="M3 20v-3a6 6 0 0 1 12 0v3M17 4a3 3 0 0 1 0 6m1 4a5 5 0 0 1 3 5"/>',
  trend:'<path d="m3 17 6-6 4 4 8-10M15 5h6v6"/>',
  book:'<path d="M12 5v16M12 5C8 2 4 3 2 4v15c4-1 7-1 10 2 3-3 6-3 10-2V4c-2-1-6-2-10 1z"/>',
  monitor:'<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8m-4-4v4"/>',
  arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',
  out:'<path d="M7 17 17 7M7 7h10v10"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  down:'<path d="m7 9 5 5 5-5"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  play:'<path d="m7 3 14 9-14 9z"/>',
  terminal:'<path d="m4 5 6 7-6 7m9 0h7"/>',
  spark:'<path d="m12 2 2.6 7.4L22 12l-7.4 2.6L12 22l-2.6-7.4L2 12l7.4-2.6z"/>',
  settings:'<path d="M4 7h16M4 17h16"/><circle cx="8" cy="7" r="3"/><circle cx="16" cy="17" r="3"/>',
  close:'<path d="m6 6 12 12M18 6 6 18"/>',
  refresh:'<path d="M20 7a9 9 0 1 0 1 8M20 2v6h-6"/>',
  shield:'<path d="m12 2 8 3v6c0 5-8 11-8 11S4 16 4 11V5z"/><path d="m8 11 3 3 5-5"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M3 16v5h18v-5"/>',
  folder:'<path d="M2 6V3h7l3 3h10v14H2z"/>',
  back:'<path d="M20 12H4m6-6-6 6 6 6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.spark}</svg>`;
const esc = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const harnesses = [
  {id:'claude',name:'Claude Code',glyph:'✳',entry:'/play',detected:true},
  {id:'codex',name:'Codex',glyph:'◆',entry:'$play',detected:true},
  {id:'cursor',name:'Cursor',glyph:'⌁',entry:'/play',detected:true},
  {id:'kimi',name:'Kimi',glyph:'●',entry:'/skill:play',detected:false},
  {id:'hermes',name:'Hermes Agent',glyph:'◈',entry:'/play',detected:false},
  {id:'opencode',name:'OpenCode',glyph:'◇',entry:'/play',detected:false},
];
const plays = [
  {id:'release',title:'Prepare a release',description:'Check changes, draft release notes, and review the next version.',group:'org',category:'Engineering',author:'Northstar Studio',prompt:'find a Play to prepare a release'},
  {id:'review',title:'Review a pull request',description:'Check correctness, tests, and the changes that deserve a second look.',group:'org',category:'Engineering',author:'Northstar Studio',prompt:'find a Play to review a pull request'},
  {id:'brief',title:'Write a customer brief',description:'Turn account research into a concise brief before your next call.',group:'invited',category:'Research',author:'Acme Platform',prompt:'find a Play to write a customer brief'},
  {id:'notes',title:'Turn meeting notes into actions',description:'Pull out decisions, owners, and the next steps.',group:'personal',category:'Productivity',author:'Your published Plays',prompt:'find a Play for meeting notes'},
  {id:'hello',title:'Hello, Play',description:'A small first run to get comfortable with Play.',group:'community',category:'Getting started',author:'Community',prompt:'run Hello'},
  {id:'github',title:'Understand a GitHub repository',description:'Explore the structure, entry points, and how to run the tests.',group:'community',category:'Engineering',author:'Community',prompt:'find a Play to understand a GitHub repository'},
  {id:'competitor',title:'Research a competitor',description:'Build a sourced overview of a product and its positioning.',group:'community',category:'Research',author:'Community',prompt:'find a Play to research a competitor'},
  {id:'pr',title:'Review a pull request before merging',description:'Inspect a proposed change and summarize the findings.',group:'community',category:'Engineering',author:'Community',prompt:'find a Play to review a pull request'},
];
const exploreExamples = [
  {
    title:'Compare competitor pricing',
    tools:'Notion + parallel-cli',
    prompt:'Connect to Notion, find my pricing page, and extract its pricing table. Use parallel-cli to find my competitors’ pricing pages and extract their pricing grids. Ask me which competitors to include, then compare prices, billing periods, plan limits, and features in a table with source links.',
  },
  {
    title:'Check whether a launch is ready',
    tools:'Notion + GitHub',
    prompt:'Find our launch checklist in Notion and the matching milestone in GitHub. Compare the checklist with open issues and pull requests. Give me a launch-readiness report with blockers, owners, and links to the work that remains.',
  },
  {
    title:'Prepare for a customer call',
    tools:'Notion + parallel-cli',
    prompt:'Find our notes about the customer in Notion. Use parallel-cli to research their product, recent announcements, and pricing. Create a meeting brief with our previous commitments, useful questions, and source links. Ask me which customer to research.',
  },
  {
    title:'Draft a release from the actual changes',
    tools:'GitHub',
    prompt:'Review the merged pull requests since the last release in my GitHub repository. Group the changes into features, fixes, and breaking changes. Draft release notes with pull-request links and flag missing tests or migration instructions. Ask me which repository to use.',
  },
];
const defaults = () => ({view:'home',step:0,email:'alex@example.com',org:'Northstar Studio',invites:[],selected:['claude','codex','cursor'],installed:['claude','codex','cursor'],harnessVersions:{claude:'0.4.98',codex:'0.4.98',cursor:'0.4.98'},preferred:'claude',machine:'existing',playVersion:'0.4.98',roteVersion:'0.84.0',query:'',scope:'all',category:'all',installPhase:0,installMode:'setup',installError:false,authProvider:'',codeSent:false});
let state = defaults();
let installTimer;
let toastTimer;
const app = document.querySelector('#app');
const modal = document.querySelector('#detail');
const harnessVersion = id => state.harnessVersions[id] || state.playVersion;
const updateAvailable = () => state.playVersion !== '0.4.99' || state.roteVersion !== '0.85.0' || state.installed.some(id => harnessVersion(id) !== '0.4.99');
const componentChange = (current, target) => current === target ? `${target} · current` : `${current} → ${target}`;
const currentHarness = () => harnesses.find(h => h.id === state.preferred) || harnesses.find(h => state.installed.includes(h.id)) || harnesses[0];
const glyph = h => `<span class="harness-glyph ${h.id}" aria-hidden="true">${h.glyph}</span>`;
const traffic = '<div class="traffic" aria-hidden="true"><i></i><i></i><i></i></div>';
const brand = '<div class="brand"><img src="assets/modiqo-wordmark.svg" alt="Modiqo"><span>play</span></div>';
const art = () => `<div class="hero-art" aria-hidden="true"><div class="orbital"></div><div class="orbital two"></div><div class="orbital three"></div><div class="play-cube">${icon('play')}</div><i class="orbit-dot"></i><i class="orbit-dot d2"></i><span class="orbit-star">✧</span></div>`;
const button = (text,action,cls='primary',extra='') => `<button class="${cls}" data-action="${action}" ${extra}>${text}</button>`;
const external = (url,label,cls='') => `<a href="${url}" target="_blank" rel="noopener noreferrer" class="${cls}">${label}</a>`;
const copyButton = text => `<button class="copy-command" data-action="copy" data-copy="${esc(text)}" aria-label="Copy ${esc(text)}"><code>${esc(text)}</code>${icon('copy')}</button>`;
const steps = ['Welcome','Your account','Your organization','Invite colleagues','Your harnesses','Install & verify'];

function toast(message){
  const node=document.querySelector('#toast');node.textContent=message;node.classList.add('show');
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.classList.remove('show'),3500);
}
function go(view){
  clearInterval(installTimer);state.view=view;render();
  history.replaceState(null,'',`#${view}`);
  document.querySelector('h1')?.focus({preventScroll:true});
}
function render(){
  app.innerHTML = state.view==='setup' ? setupShell() : mainShell();
  document.querySelector('h1')?.setAttribute('tabindex','-1');
  document.querySelectorAll('h1').forEach(el=>el.style.outline='none');
}
function navItem(view,label,name,count=''){
  return `<button data-action="nav" data-view="${view}" class="${state.view===view?'active':''}" ${state.view===view?'aria-current="page"':''}>${icon(name)}${label}${count?`<span class="count">${count}</span>`:''}${view==='search'?'<kbd>⌘ K</kbd>':''}</button>`;
}
function mainShell(){
  const titles={home:'Home',search:'Search Plays',harnesses:'Your harnesses',organizations:'Organizations',updates:'Updates'};
  return `<div class="window"><aside class="sidebar">${traffic}${brand}
    <button class="workspace" data-action="nav" data-view="organizations"><span class="avatar">${esc((state.org||'Personal').split(' ').map(s=>s[0]).join('').slice(0,2).toUpperCase())}</span><span class="ws-text">${esc(state.org||'Personal')}<small>${state.org?'Company organization':'Your account'}</small></span>${icon('down')}</button>
    <nav class="nav" aria-label="Main navigation">${navItem('home','Home','home')}${navItem('search','Search Plays','search')}${navItem('harnesses','Your harnesses','monitor',state.installed.length)}
      <div class="eyebrow">Discover</div>
      ${external('https://www.modiqo.ai/feed',`${icon('grid')}Community Plays${icon('out').replace('<svg','<svg class="out"')}`)}
      ${external('https://www.modiqo.ai/profiles',`${icon('users')}Playmakers${icon('out').replace('<svg','<svg class="out"')}`)}
      ${external('https://www.modiqo.ai/trending',`${icon('trend')}Trending${icon('out').replace('<svg','<svg class="out"')}`)}
      ${external('https://www.modiqo.ai/docs',`${icon('book')}Documentation${icon('out').replace('<svg','<svg class="out"')}`)}
      <div class="eyebrow">Manage</div>${navItem('organizations','Organizations','folder')}${navItem('updates','Updates','refresh',updateAvailable()?'1':'')}
    </nav><div class="side-bottom"><div class="health"><span class="dot"></span> ${state.installed.length} ${state.installed.length===1?'harness':'harnesses'} ready</div><div class="profile"><span class="avatar">A</span><div>Alex Morgan<small>Personal account</small></div><button data-action="account" aria-label="Account details">${icon('settings')}</button></div></div>
    </aside><main class="main"><header class="topbar"><div class="topbar-left">${icon('grid')}<span>${titles[state.view]||'Home'}</span><select class="mobile-nav" data-change="nav" aria-label="Navigate">${Object.entries(titles).map(([id,title])=>`<option value="${id}" ${state.view===id?'selected':''}>${title}</option>`).join('')}</select></div><div class="topbar-right">${external('https://www.modiqo.ai/account',`${icon('users')}Create an organization ${icon('out')}`,'account-link')}<span class="version"><span class="dot"></span> Play ${state.playVersion}</span><button class="icon-button" data-action="nav" data-view="search" aria-label="Search Plays">${icon('search')}</button></div></header><div class="content">${({home:home,search:search,harnesses:harnessPage,organizations:orgPage,updates:updatesPage}[state.view]||home)()}</div></main></div>`;
}
function harnessCard(h){
  return `<article class="harness-card"><div class="harness-title">${glyph(h)}<div><h3>${h.name}</h3><small><span class="dot"></span>Play ${harnessVersion(h.id)} installed</small></div></div>${state.preferred===h.id?'<span class="preferred" title="Preferred harness" aria-label="Preferred harness">✦</span>':''}<div class="harness-footer"><code>${esc(h.entry)}</code><button data-action="open-harness" data-id="${h.id}" aria-label="Open ${h.name}">Open ${icon('out')}</button></div></article>`;
}
function home(){
  const h=currentHarness();
  const guide=[['Meet Play','Start a fresh conversation in your harness.',''],['See what’s new','A short list of new community Plays.',"what's new"],['Run your first Play','Try a small run before your own work.','run Hello'],['Explore a real task','Start with a goal. Try an example below.','explore']];
  return `<div class="page"><section class="hero"><div><div class="eyebrow">Your next good idea starts here</div><h1>You’re ready to Play.</h1><p>Your tools are connected. Find a Play, try something new,<br>or make your next great piece of work repeatable.</p></div>${art()}</section>
    ${updateAvailable()?`<button class="update-strip" data-action="nav" data-view="updates"><span class="update-strip-icon">${icon('download')}</span><span><strong>A fresh version is ready.</strong> Update Play and Rote together.</span><span class="update-strip-cta">Review update ${icon('arrow')}</span></button>`:''}
    <section aria-label="Installed harnesses"><div class="section-heading"><h2>Installed on <span class="badge gray">${state.installed.length} ${state.installed.length===1?'harness':'harnesses'}</span></h2><button class="link-button" data-action="nav" data-view="harnesses">Manage harnesses ${icon('arrow')}</button></div><div class="harness-grid">${harnesses.filter(h=>state.installed.includes(h.id)).map(harnessCard).join('')}</div></section>
    <section class="guide"><div class="guide-head"><div><h2>A little guidance. A lot you can do.</h2><p>Your quick-start cheat sheet, one prompt at a time.</p></div><label class="harness-picker">${icon('terminal')}<select data-change="preferred" aria-label="Preferred harness">${harnesses.filter(h=>state.installed.includes(h.id)).map(x=>`<option value="${x.id}" ${x.id===h.id?'selected':''}>${x.name}</option>`).join('')}</select></label></div><div class="guide-list">${guide.map(([title,desc,cmd],i)=>`<div class="guide-row"><span class="step-num">${i+1}</span><div><h3>${title}</h3><p>${desc}</p></div>${copyButton(`${h.entry}${cmd?' '+cmd:''}`)}${cmd==='explore'?`<div class="explore-examples" aria-label="Explore example prompts">${exploreExamples.map(example=>`<article class="explore-example"><div class="example-heading"><span class="eyebrow">${esc(example.tools)}</span><button class="example-copy" data-action="copy" data-copy="${esc(`${h.entry} explore ${example.prompt}`)}" aria-label="Copy prompt: ${esc(example.title)}">${icon('copy')}Copy prompt</button></div><h3>${esc(example.title)}</h3><p>${esc(example.prompt)}</p></article>`).join('')}<p class="example-note">Example prompts for your own work. Play guides you through connecting the tools you need.</p></div>`:''}</div>`).join('')}</div></section>
    <div class="discovery"><button class="discover-card" data-action="nav" data-view="search"><span class="discover-icon">${icon('search')}</span><div><h3>There’s a Play for that.</h3><p>Search your teams and the community.</p></div>${icon('arrow')}</button>${external('https://www.modiqo.ai/trending',`<span class="discover-icon">${icon('trend')}</span><div><h3>See what’s catching on.</h3><p>Explore trending community Plays.</p></div>${icon('out')}`,'discover-card')}</div>
    <footer class="bottom-note"><span>Made for your tools. Ready when you are.</span>${external('https://www.modiqo.ai/blog/the-playoffs',`The Playoffs field guide ${icon('out')}`)}</footer></div>`;
}
function search(){
  return `<div class="page"><div class="page-title"><div class="eyebrow">A good place to start</div><h1>What do you want to do?</h1><p>Find published Plays from your organizations and the community.</p></div><div class="search-box">${icon('search')}<input id="search-input" type="search" placeholder="Try “review a pull request”" value="${esc(state.query)}" aria-label="Search published Plays"><kbd>⌘ K</kbd></div><div class="filter-row">${[['all','Everything'],['community','Community'],['personal','My Plays'],['orgs','My organizations']].map(([id,label])=>`<button data-action="scope" data-scope="${id}" class="${state.scope===id?'active':''}" aria-pressed="${state.scope===id}">${label}</button>`).join('')}<select data-change="scope-org" aria-label="Search a specific organization"><option value="">Specific organization</option>${state.org?`<option value="org" ${state.scope==='org'?'selected':''}>${esc(state.org)}</option>`:''}<option value="invited" ${state.scope==='invited'?'selected':''}>Acme Platform</option></select><select data-change="category" aria-label="Filter by category"><option value="all">All categories</option>${['Engineering','Research','Productivity','Getting started'].map(x=>`<option ${state.category===x?'selected':''}>${x}</option>`).join('')}</select></div><div id="results">${searchResults()}</div></div>`;
}
function searchResults(){
  const words=state.query.toLowerCase().trim().split(/\s+/).filter(Boolean);
  const results=plays.filter(p=>(p.group!=='org'||state.org)&&(!words.length||words.every(w=>(p.title+' '+p.description+' '+p.category).toLowerCase().includes(w)))&&(state.scope==='all'||state.scope===p.group||(state.scope==='orgs'&&['org','invited'].includes(p.group)))&&(state.category==='all'||state.category===p.category));
  if(!results.length)return `<div class="empty-state">${icon('search')}<h2>No matching Plays here.</h2><p>Try a shorter phrase or another category.</p>${button('Clear filters','clear-search','quiet')}</div>`;
  const groups=[['org',state.org,'Private'],['invited','Acme Platform','Private'],['personal','Your published Plays','Personal'],['community','Community','Public']];
  return `<div class="results-note">${icon('info')}Sample results · ${results.length} published Plays · live search connects in the native app</div>${groups.map(([id,label,visibility])=>{const rows=results.filter(p=>p.group===id);return rows.length?`<section class="result-group"><h2>${icon(id==='community'?'grid':'folder')}${esc(label)}<span>${rows.length}</span></h2>${rows.map(p=>`<button class="result-row" data-action="play-detail" data-id="${p.id}"><span class="result-symbol">${icon('play')}</span><span class="result-body"><h3>${p.title}</h3><p>${p.description}</p></span><span class="badge ${id==='community'?'gray':''}">${visibility}</span>${icon('chevron')}</button>`).join('')}</section>`:''}).join('')}`;
}
function harnessPage(){
  return `<div class="page"><div class="page-title"><div class="eyebrow">Your setup, at a glance</div><h1>Play, where you work.</h1><p>See where Play is installed, choose your preferred harness, and keep everything current.</p></div><div class="section-heading"><h2>Installed on this Mac <span class="badge gray">${state.installed.length}</span></h2>${button('Manage installation','manage-install','link-button')}</div><div class="manage-list">${harnesses.filter(h=>state.installed.includes(h.id)).map(h=>`<article class="manage-card">${glyph(h)}<div class="manage-body"><h3>${h.name} ${state.preferred===h.id?'<span class="badge orange">Preferred</span>':''}</h3><p><span class="dot"></span> Play ${harnessVersion(h.id)} installed · Rote ${state.roteVersion} · Verified in demo</p></div><div class="manage-actions">${copyButton(h.entry)}${button(state.preferred===h.id?'Preferred':'Make preferred','make-preferred','secondary',`data-id="${h.id}" ${state.preferred===h.id?'disabled':''}`)}${button(`Open ${icon('out')}`,'open-harness','secondary',`data-id="${h.id}"`)}</div></article>`).join('')}</div><div class="callout">${icon('info')}<span>Installing Play adds its skills and configuration to your selected harnesses. Your harness sign-in stays with each app.</span></div><div class="runtime-card"><div><small>Play</small><strong>${state.playVersion}</strong></div><div><small>Rote</small><strong>${state.roteVersion}</strong></div><div><small>Architecture</small><strong>Apple Silicon · demo</strong></div><div><small>Last verified</small><strong>Just now · demo</strong></div></div><div style="margin-top:25px">${button(`${icon('refresh')} ${updateAvailable()?'Update Play + Rote':'Check for updates'}`,'nav','secondary','data-view="updates"')}</div></div>`;
}
function updatesPage(){
  const newer=updateAvailable();
  const integrationsOnly=newer&&state.playVersion==='0.4.99'&&state.roteVersion==='0.85.0';
  return `<div class="page"><div class="page-title"><div class="eyebrow">Keep your setup in step</div><h1>${integrationsOnly?'Bring every harness up to date.':newer?'A fresh version of Play.':'You’re up to date.'}</h1><p>One update keeps Play, Rote, and your installed harness integrations together.</p></div><div class="update-hero"><div class="update-app-icon">${icon(newer?'download':'check')}</div><div><h2>${integrationsOnly?'A harness update is ready':newer?'Play 0.4.99 is ready':'All set for your next Play'}</h2><p>${integrationsOnly?'Play and Rote are current. Refresh the remaining harness integrations.':newer?'Includes Rote 0.85.0 and updated Play integrations.':'Play 0.4.99 and Rote 0.85.0 are installed in this demo.'}</p><span class="badge ${newer?'orange':''}">${newer?'Update available':'Current version'}</span></div></div><div class="plan-list"><div class="plan-row"><span>Play</span><span>${componentChange(state.playVersion,"0.4.99")}</span></div><div class="plan-row"><span>Rote</span><span>${componentChange(state.roteVersion,"0.85.0")}</span></div><div class="plan-row"><span>Harness integrations</span><small>${harnesses.filter(h=>state.installed.includes(h.id)).map(h=>h.name).join(', ')}</small></div><div class="plan-row"><span>Your existing configuration</span><span class="badge">Back up before updating</span></div></div>${newer?button(`${icon('refresh')} Update Play + Rote`,'review-update'):button(`${icon('refresh')} Check for updates`,'check-updates','secondary')}<div class="callout">${icon('shield')}<span>The update plan checks existing versions, backs up configuration, updates both components, and verifies each installed harness.</span></div><p class="fine-print">Prototype versions are sample state. No software is downloaded or changed.</p><div class="state-links"><button data-action="demo-update">Preview an available update</button></div></div>`;
}
function orgPage(){
  return `<div class="page"><div class="page-title"><div class="eyebrow">Better together</div><h1>Your organizations.</h1><p>Keep company Plays private and share the work with your team.</p></div><section class="org-section"><h2>Organizations you own</h2>${state.org?`<div class="org-row"><span class="avatar">${esc(state.org[0].toUpperCase())}</span><div class="org-body"><h3>${esc(state.org)}</h3><small>You’re the owner · ${1+state.invites.length} ${state.invites.length?'members / pending invitations':'member'}</small></div><span class="badge orange">Owner</span>${button('Invite','invite-from-home','secondary')}</div>`:`<div class="callout">You haven’t created an organization yet.</div>`}${button(`${icon('users')} Create an organization`,'create-org','secondary')}</section><section class="org-section"><h2>Organizations you’ve joined</h2><div class="org-row"><span class="avatar">AP</span><div class="org-body"><h3>Acme Platform</h3><small>Invited by a colleague · sample organization</small></div><span class="badge gray">Member</span>${button('Find Plays','org-search','secondary')}</div></section><div class="callout">${icon('shield')}<span>Only published Plays join search. Private organization Plays are visible to members with access.</span></div></div>`;
}

function setupShell(){
  return `<div class="window setup-window"><aside class="sidebar setup-side">${traffic}${brand}<div class="setup-tagline">Good work.<br><span>Worth repeating.</span></div><nav class="setup-steps" aria-label="Setup progress">${steps.map((label,i)=>`<div class="setup-step ${state.step===i?'current':state.step>i?'done':''}" ${state.step===i?'aria-current="step"':''}><b>${state.step>i?icon('check'):String(i+1).padStart(2,'0')}</b><span>${label}</span></div>`).join('')}</nav><div class="setup-side-footer"><strong>Your tools. Your team. Your Plays.</strong><br>A little setup goes a long way.</div></aside><main class="setup-main"><header class="setup-top"><span>PLAY FOR MAC</span><span>${state.step===6?'Ready to go':`Step ${state.step+1} of 6`}</span></header><div class="setup-body">${[welcome,account,organization,invites,harnessSelection,installView,complete][state.step]()}</div><footer class="setup-bottom">${state.step>0&&state.step<5?button(`${icon('back')} Back`,'back','link-button'):'<span>Apple Silicon + Intel</span>'}<span>Interactive demo · no system changes</span></footer></main></div>`;
}
function welcome(){
  return `<div class="welcome-art">${art()}</div><div class="eyebrow">A home for your next Play</div><h1>Make good work<br>worth repeating.</h1><p>Set up Play in the tools you already use. Then find, run, and share Plays with your team.</p><div class="machine-switch" role="group" aria-label="Demo machine state">${button('Existing installation','machine','',`data-machine="existing" aria-pressed="${state.machine==='existing'}"`)}${button('Fresh Mac','machine','',`data-machine="fresh" aria-pressed="${state.machine==='fresh'}"`)}</div><div class="detected-panel"><div>${icon('monitor')}<strong>${state.machine==='existing'?'We found your setup.':'Let’s get your Mac ready.'}</strong><span class="badge gray">Demo</span></div><p>${state.machine==='existing'?`Play ${state.playVersion} · Rote ${state.roteVersion}<br>Your configuration will be backed up before any update.`:'Play and Rote aren’t installed in this scenario.<br>Setup prepares the runtime before sign-in.'}</p></div><div class="welcome-features"><div>${icon('check')}Sign in with Google, GitHub, or email</div><div>${icon('check')}Bring your team, or start on your own</div><div>${icon('check')}Choose where Play should be installed</div></div>${button(`${state.machine==='existing'?'Continue with your setup':'Set up Play'} ${icon('arrow')}`,'next','primary block')}<div class="fine-print">A few steps now. Ready for your next good idea.</div>`;
}
function account(){
  if(state.codeSent)return `<div class="eyebrow">One code. You’re in.</div><h1>Check your email.</h1><p>Enter the six-digit code for <strong>${esc(state.email)}</strong>.</p><form data-form="verify"><div class="form-field"><label for="code">One-time code</label><input id="code" name="code" class="code-input" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" minlength="6" maxlength="6" required placeholder="000000" aria-describedby="code-help"><small id="code-help">For this prototype, use 123456. No email was sent.</small></div><div class="error" id="form-error" role="alert"></div><button class="primary block" type="submit">Verify and continue ${icon('arrow')}</button></form><div class="state-links"><button data-action="resend">Resend code</button><button data-action="change-email">Use another email</button></div>`;
  return `<div class="eyebrow">Your Plays follow you</div><h1>Make yourself at home.</h1><p>Sign in or create an account. Use the same account you use on Modiqo.</p><div class="auth-options">${button('<span class="provider" aria-hidden="true">G</span> Google','oauth','secondary','data-provider="Google"')}${button(`${icon('terminal')} GitHub`,'oauth','secondary','data-provider="GitHub"')}</div><div class="separator">or continue with email</div><form data-form="email"><div class="form-field"><label for="email">Work or personal email</label><input id="email" name="email" type="email" autocomplete="email" placeholder="you@company.com" value="${state.email==='alex@example.com'?'':esc(state.email)}" required></div><button class="primary block" type="submit">Email me a code ${icon('arrow')}</button></form><div class="fine-print">Demo sign-in. No account is created and no email is sent.</div>${state.machine==='existing'?`<div class="callout">${icon('info')}<span>The native app checks your existing Rote sign-in before reusing it.</span></div>`:''}`;
}
function organization(){
  return `<div class="eyebrow">Make room for your team</div><h1>A home for company Plays.</h1><p>Create an organization to publish private Plays and share them with your colleagues.</p><form data-form="org"><div class="form-field"><label for="org">Company or organization name</label><input id="org" name="org" placeholder="e.g. Northstar Studio" value="${esc(state.org)}" maxlength="80" required></div><div class="callout">${icon('shield')}<span><strong>You’ll be the owner.</strong><br>You choose who joins and who can co-manage your Plays.</span></div><button class="primary block" type="submit">Create organization ${icon('arrow')}</button></form>${button('I’m using Play on my own','skip-org','quiet block')}<div class="fine-print">This creates a sample organization in the prototype only.</div>`;
}
function invites(){
  return `<div class="eyebrow">Good work is a team sport</div><h1>Bring your people.</h1><p>Invite colleagues to ${esc(state.org||'your organization')}. You can always do this later.</p><form data-form="invite"><label for="invite-email">Colleague’s email</label><div class="invitation"><input type="email" id="invite-email" name="inviteEmail" required placeholder="colleague@company.com"><select class="field" name="role" aria-label="Invitation role"><option value="Admin">Co-manager</option><option value="Member">Member</option></select></div><div class="error" id="form-error" role="alert"></div><button class="quiet" type="submit">+ Add colleague</button></form><div class="invite-list">${state.invites.map((x,i)=>`<div class="invite-pill">${icon('users')}<span>${esc(x.email)}</span><small>${x.role==='Admin'?'Co-manager':'Member'}</small><button data-action="remove-invite" data-index="${i}" aria-label="Remove ${esc(x.email)}">${icon('close')}</button></div>`).join('')}</div><div class="callout">${icon('info')}<span>Co-managers can manage Plays and members. Members can use and contribute team Plays.</span></div>${button(`${state.invites.length?`Invite ${state.invites.length} ${state.invites.length===1?'colleague':'colleagues'} & continue`:'Continue without invitations'} ${icon('arrow')}`,'next','primary block')}<div class="fine-print">Invitations are simulated. No messages are sent.</div>`;
}
function harnessSelection(){
  return `<div class="eyebrow">Meet your tools where they are</div><h1>Your tools. Now with Play.</h1><p>We found three harnesses in this demo. Choose where to ${state.machine==='existing'?'install or update':'install'} Play.</p><div class="setup-harnesses">${harnesses.filter(h=>h.detected).map(h=>`<label class="harness-choice ${state.selected.includes(h.id)?'selected':''}"><input type="checkbox" value="${h.id}" data-change="harness" ${state.selected.includes(h.id)?'checked':''}>${glyph(h)}<span class="choice-label">${h.name}<small>${state.machine==='existing'&&state.installed.includes(h.id)?`Play ${harnessVersion(h.id)} found · ${harnessVersion(h.id)==='0.4.99'?'up to date':'update available'}`:'Detected · ready to install Play'}</small></span><span class="badge gray">${esc(h.entry)}</span></label>`).join('')}</div><details><summary>Other supported harnesses</summary><p>Kimi, Hermes Agent, and OpenCode aren’t detected in this sample setup. The native app will check installed harnesses.</p></details><div class="callout">${icon('shield')}<span>${state.machine==='existing'?'Existing setup found. Your configuration is backed up before updates.':'Setup installs Play and Rote, then checks each selected harness.'}</span></div>${button(`Review setup ${icon('arrow')}`,'review-install','primary block',state.selected.length?'':'disabled')}`;
}
const phases=['Back up existing configuration','Install Rote 0.85.0','Install Play 0.4.99','Connect selected harnesses','Verify your setup'];
function installView(){
  if(state.installError)return `<div class="install-symbol">${icon('info')}</div><div class="eyebrow">Your progress is saved</div><h1>Let’s try that again.</h1><p>The demo download was interrupted. Your existing configuration is unchanged in this prototype.</p><div class="callout">${icon('refresh')}<span>Resume at <strong>${phases[state.installPhase]}</strong>. Completed steps stay completed.</span></div>${button('Retry this step','retry-install','primary block')}${button('Return to harness selection','cancel-install','quiet block')}`;
  return `<div class="install-symbol">${icon('download')}</div><div class="eyebrow">A little setup, a lot of possibility</div><h1>${state.installMode==='update'?'Keeping you up to date.':'Making room for Play.'}</h1><p>${state.installMode==='update'?'Updating Play and Rote together, then checking your harnesses.':'Preparing Play and Rote for the harnesses you selected.'}</p><div class="install-track" role="progressbar" aria-label="Simulated installation progress" aria-valuemin="0" aria-valuemax="5" aria-valuenow="${state.installPhase}"><span style="width:${state.installPhase/5*100}%"></span></div><div aria-live="polite">${phases.map((p,i)=>`<div class="install-step ${i<state.installPhase?'done':i===state.installPhase?'running':''}">${i<state.installPhase?icon('check'):i===state.installPhase?'<span class="spinner"></span>':'<span class="empty-circle"></span>'}<span>${p}</span><span class="step-detail">${i<state.installPhase?'Done':i===state.installPhase?'In progress':''}</span></div>`).join('')}</div><details><summary>View installation details</summary><pre>Demo mode: no commands executed.
${phases.slice(0,state.installPhase).map(p=>`✓ ${p}`).join('\n')}
${state.selected.map(id=>`${id}: selected for verification`).join('\n')}</pre></details><div class="state-links"><button data-action="fail-install">Preview a recoverable error</button></div>`;
}
function complete(){
  return `<div class="install-symbol" style="background:var(--green-soft);color:var(--green)">${icon('check')}</div><div class="eyebrow">All set</div><h1>${state.installMode==='update'?'Fresh tools. Same good work.':'You’re ready to Play.'}</h1><p>Play and Rote are ready in your selected harnesses. Here’s where you can start.</p><div class="success-banner">${icon('check')}Play ${state.playVersion} + Rote ${state.roteVersion} · verified in demo</div><div class="section-heading"><h2>Installed on</h2><span class="eyebrow">${state.installed.length} ${state.installed.length===1?'harness':'harnesses'}</span></div><div class="harness-grid">${harnesses.filter(h=>state.installed.includes(h.id)).map(harnessCard).join('')}</div>${button(`Go to my home ${icon('arrow')}`,'finish','primary block')}<div class="fine-print">Your cheat sheet and community are waiting.</div>`;
}
function startInstall(mode='setup',resume=false){
  clearInterval(installTimer);state.installMode=mode;state.installError=false;
  if(!resume)state.installPhase=0;
  state.view='setup';state.step=5;render();
  installTimer=setInterval(()=>{
    state.installPhase++;
    if(state.installPhase>=phases.length){
      clearInterval(installTimer);
      state.installed=state.machine==='fresh'?[...state.selected]:[...new Set([...state.installed,...state.selected])];
      state.selected.forEach(id=>state.harnessVersions[id]='0.4.99');
      state.playVersion='0.4.99';state.roteVersion='0.85.0';
      if(!state.installed.includes(state.preferred))state.preferred=state.installed[0];
      state.step=6;
    }
    render();
  },1350);
}
function showModal(content){
  modal.innerHTML=`<div class="dialog-top"><span class="eyebrow">Play for Mac</span><button class="icon-button" data-action="close-modal" aria-label="Close dialog">${icon('close')}</button></div>${content}`;
  if(!modal.open)modal.showModal();
}
function reviewInstall(update=false){
  if(update){state.selected=[...state.installed];state.machine='existing';}
  showModal(`<h2>${update?'Update Play + Rote':'Your setup, before we start.'}</h2><p>${update?'Update both components and refresh Play in your installed harnesses.':'Review what this setup adds or updates on your Mac.'}</p><div class="plan-list"><div class="plan-row"><span>Play</span><small>${componentChange(state.machine==='fresh'&&!update?'Not installed':state.playVersion,'0.4.99')}</small></div><div class="plan-row"><span>Rote</span><small>${componentChange(state.machine==='fresh'&&!update?'Not installed':state.roteVersion,'0.85.0')}</small></div><div class="plan-row"><span>Harnesses</span><small>${harnesses.filter(h=>state.selected.includes(h.id)).map(h=>h.name).join(', ')}</small></div><div class="plan-row"><span>Configuration backup</span><span class="badge">Before changes</span></div></div><p>Prototype only: this previews the installation without changing your Mac.</p><div class="dialog-actions">${button(`${update?'Update Play + Rote':'Install Play + Rote'} ${icon('arrow')}`,update?'confirm-update':'confirm-install')}${button('Go back','close-modal','secondary')}</div>`);
}

document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action]');if(!target)return;
  const action=target.dataset.action;
  if(action==='nav'){go(target.dataset.view);return;}
  if(action==='preview-home'){go('home');return;}
  if(action==='restart'){clearInterval(installTimer);state.step=0;state.codeSent=false;go('setup');return;}
  if(action==='theme'){document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark';return;}
  if(action==='next'){state.step++;render();document.querySelector('h1')?.focus();return;}
  if(action==='back'){if(state.step===4&&!state.org)state.step=2;else state.step--;render();return;}
  if(action==='machine'){state.machine=target.dataset.machine;render();return;}
  if(action==='oauth'){state.authProvider=target.dataset.provider;showModal(`<h2>Continue with ${esc(state.authProvider)}.</h2><p>The native app opens your browser to sign in using the existing Rote flow, then returns you here.</p><p>This prototype uses a sample account.</p>${button('Simulate successful sign-in','oauth-success','primary block')}`);return;}
  if(action==='oauth-success'){modal.close();state.email='alex@example.com';state.step=2;render();return;}
  if(action==='change-email'){state.codeSent=false;render();return;}
  if(action==='resend'){toast('Demo code: 123456. No email was sent.');return;}
  if(action==='skip-org'){state.org='';state.invites=[];state.step=4;render();return;}
  if(action==='remove-invite'){state.invites.splice(Number(target.dataset.index),1);render();return;}
  if(action==='review-install'){reviewInstall();return;}
  if(action==='review-update'){reviewInstall(true);return;}
  if(action==='confirm-install'||action==='confirm-update'){modal.close();startInstall(action==='confirm-update'?'update':'setup');return;}
  if(action==='close-modal'){modal.close();return;}
  if(action==='fail-install'){clearInterval(installTimer);state.installError=true;render();return;}
  if(action==='retry-install'){startInstall(state.installMode,true);return;}
  if(action==='cancel-install'){clearInterval(installTimer);state.installError=false;state.step=4;render();return;}
  if(action==='finish'){go('home');return;}
  if(action==='copy'){
    try{await navigator.clipboard.writeText(target.dataset.copy);toast('Prompt copied. Paste it into a fresh harness conversation.');}catch{toast('Clipboard unavailable. Select and copy the prompt.');}
    return;
  }
  if(action==='make-preferred'){state.preferred=target.dataset.id;render();toast(`${currentHarness().name} is your preferred harness.`);return;}
  if(action==='open-harness'){
    const h=harnesses.find(h=>h.id===target.dataset.id);
    showModal(`<span class="badge">Play ${harnessVersion(h.id)} installed</span><h2>Start in ${h.name}.</h2><p>Open a fresh conversation, then paste this prompt.</p>${copyButton(h.entry)}<p>The native app will open ${h.name}. This prototype only copies the prompt.</p>${button('Got it','close-modal','secondary')}`);return;
  }
  if(action==='manage-install'){state.selected=[...state.installed];state.machine='existing';state.step=4;go('setup');return;}
  if(action==='check-updates'){toast('Demo check complete. Play and Rote are up to date.');return;}
  if(action==='demo-update'){state.playVersion='0.4.98';state.roteVersion='0.84.0';state.installed.forEach(id=>state.harnessVersions[id]='0.4.98');render();return;}
  if(action==='scope'){state.scope=target.dataset.scope;render();return;}
  if(action==='clear-search'){state.query='';state.category='all';state.scope='all';render();document.querySelector('#search-input').focus();return;}
  if(action==='org-search'){state.scope='invited';state.query='';go('search');return;}
  if(action==='create-org'){state.step=2;go('setup');return;}
  if(action==='invite-from-home'){state.step=3;go('setup');return;}
  if(action==='play-detail'){
    const p=plays.find(p=>p.id===target.dataset.id);const h=currentHarness();
    showModal(`<span class="badge ${p.group==='community'?'gray':''}">${p.group==='community'?'Community · Public':p.group==='org'?esc(state.org)+' · Private':p.group==='invited'?'Acme Platform · Private':'Your published Plays'}</span><h2>${p.title}</h2><p>${p.description}</p><div class="eyebrow" style="margin:20px 0 10px">Try it in ${h.name}</div>${copyButton(`${h.entry} ${p.prompt}`)}<p>Sample Play for design review. Copying a prompt does not run a Play.</p><div class="dialog-actions">${button('Done','close-modal','secondary')}${external('https://www.modiqo.ai/feed',`Browse live community ${icon('out')}`,'quiet')}</div>`);return;
  }
  if(action==='account'){showModal(`<h2>Your account.</h2><p>Alex Morgan · ${esc(state.email)}</p><div class="callout">${icon('info')}<span>This is a sample account. The native app uses your existing Rote sign-in.</span></div>${button('Preview sign-in','account-setup','secondary')}`);return;}
  if(action==='account-setup'){modal.close();state.step=1;state.codeSent=false;go('setup');}
});
document.addEventListener('change',event=>{
  const target=event.target;const type=target.dataset.change;
  if(type==='nav'){go(target.value);return;}
  if(type==='preferred'){state.preferred=target.value;render();}
  if(type==='harness'){state.selected=target.checked?[...new Set([...state.selected,target.value])]:state.selected.filter(x=>x!==target.value);render();document.querySelector(`input[value="${target.value}"]`)?.focus();}
  if(type==='scope-org'){state.scope=target.value||'all';render();}
  if(type==='category'){state.category=target.value;render();}
});
document.addEventListener('input',event=>{
  if(event.target.id==='search-input'){state.query=event.target.value;document.querySelector('#results').innerHTML=searchResults();}
});
document.addEventListener('submit',event=>{
  const type=event.target.dataset.form;if(!type)return;event.preventDefault();const data=new FormData(event.target);
  if(type==='email'){state.email=data.get('email').trim();state.codeSent=true;render();document.querySelector('#code').focus();}
  if(type==='verify'){if(data.get('code')!=='123456'){document.querySelector('#form-error').textContent='Use 123456 to continue in this prototype.';return;}state.step=2;render();}
  if(type==='org'){const name=data.get('org').trim();if(!name){event.target.querySelector('input').focus();return;}state.org=name;state.step=3;render();}
  if(type==='invite'){
    const email=data.get('inviteEmail').trim();
    if(state.invites.some(x=>x.email.toLowerCase()===email.toLowerCase())){document.querySelector('#form-error').textContent='That colleague is already on your invitation list.';return;}
    if(email.toLowerCase()===state.email.toLowerCase()){document.querySelector('#form-error').textContent='You’re already the owner. Add a colleague’s email.';return;}
    state.invites.push({email,role:data.get('role')});render();document.querySelector('#invite-email').focus();
  }
});
document.addEventListener('keydown',event=>{
  if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){
    event.preventDefault();if(modal.open)modal.close();go('search');document.querySelector('#search-input')?.focus();
  }
});
modal.addEventListener('click',event=>{if(event.target===modal){const r=modal.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)modal.close();}});
const initial=location.hash.slice(1);
if(['home','search','harnesses','organizations','updates','setup'].includes(initial))state.view=initial;
render();
