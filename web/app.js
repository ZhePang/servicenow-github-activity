'use strict';
const $ = id => document.getElementById(id);
const state = {meta:null,start:null,end:null,preset:'7',sort:'momentum',search:'',repo:null,bots:false,offset:0};
let controller, chart, searchTimer;
const number = n => new Intl.NumberFormat('en-US').format(n);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const utc = value => value ? new Date(value).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) + ' UTC' : 'Unknown';
const repoUrl = name => 'https://github.com/' + name.split('/').map(encodeURIComponent).join('/');
const duration = seconds => seconds == null ? 'Unavailable' : seconds < 60 ? `${seconds.toFixed(1)}s` : seconds < 3600 ? `${(seconds/60).toFixed(1)}m` : seconds < 86400 ? `${(seconds/3600).toFixed(1)}h` : `${(seconds/86400).toFixed(1)}d`;
const inputDate = date => new Date(date).toISOString().slice(0,19);
const names = {WatchEvent:'Stars',PullRequestEvent:'PR events',IssuesEvent:'Issues',PushEvent:'Pushes',IssueCommentEvent:'Issue / PR comments',PullRequestReviewEvent:'Reviews',PullRequestReviewCommentEvent:'Inline review comments',CreateEvent:'Branch / tag creation',DeleteEvent:'Branch / tag deletion',ForkEvent:'Forks',ReleaseEvent:'Releases'};
const colors = {WatchEvent:'#b8860b',PullRequestEvent:'#2563eb',IssuesEvent:'#7c3aed',PushEvent:'#3a7b79',IssueCommentEvent:'#c6674c',PullRequestReviewEvent:'#667ca9',PullRequestReviewCommentEvent:'#99629d'};

async function get(url, signal) {
  const response = await fetch(url,{signal});
  const body = await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map(e => e.message || e.msg).join(' ') : body.detail;
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return body;
}
function params() { return new URLSearchParams({start:state.start,end:state.end}); }
function preset(value) {
  state.preset=value;
  state.end=state.meta.coverage_end;
  const earliest=new Date(state.meta.coverage_start).getTime();
  state.start=value==='all' ? state.meta.coverage_start : new Date(Math.max(earliest,new Date(state.end).getTime()-Number(value)*86400000)).toISOString();
  setInputs(); state.offset=0;
}
function setInputs() {
  $('start').value=inputDate(state.start);$('end').value=inputDate(state.end);
  for (const button of document.querySelectorAll('[data-preset]')) button.classList.toggle('active',button.dataset.preset===state.preset);
}
async function load(refreshMeta=false) {
  if (controller) controller.abort();
  const current=controller=new AbortController();
  $('status').className='';$('status').textContent='Loading activity...';$('view').classList.add('loading');
  try {
    if (!state.meta || refreshMeta) {
      state.meta=await get('/api/meta',current.signal);
      $('dataset').innerHTML=`<strong>Data through ${escape(utc(state.meta.watermark))}</strong>${number(state.meta.unique_event_count)} events across ${number(state.meta.repository_count)} repositories`;
      if (!state.meta.coverage_start) {
        $('view').innerHTML='<div class="panel empty">No events have been imported. Run the snapshot importer or submit an event to the API.</div>';
        $('status').textContent='';return;
      }
      if (!state.start || state.preset!=='custom') preset(state.preset);
      for (const id of ['start','end']) {$(id).min=inputDate(state.meta.coverage_start);$(id).max=inputDate(state.meta.coverage_end);}
    }
    const query=params();
    if (state.repo) {
      query.set('include_bots',state.bots);query.set('pr_offset',state.offset);query.set('pr_limit',25);
      const report=await get(`/api/repos/${state.repo}?${query}`,current.signal);
      if (current!==controller) return;
      renderRepo(report);
    } else {
      query.set('sort',state.sort);query.set('q',state.search);
      const report=await get(`/api/trending?${query}`,current.signal);
      if (current!==controller) return;
      renderTrends(report);
    }
    $('status').textContent='';
  } catch (error) {
    if (error.name==='AbortError') return;
    $('status').className='error';$('status').innerHTML=`${escape(error.message)} <button id="retry">Retry</button>`;
    $('retry').onclick=()=>load(true);
  } finally {
    if (current===controller) $('view').classList.remove('loading');
  }
}
function renderTrends(report) {
  const searching=document.activeElement?.id==='search';
  const selection=searching?[$('search').selectionStart,$('search').selectionEnd]:null;
  if (chart) {chart.destroy();chart=null;}
  const rows=report.repositories.map((r,i)=>`<tr><td class="rank">${i+1}</td><td class="repo-cell"><button data-repo="${r.repo_id}">${escape(r.repo_name)}</button></td><td class="number">${number(r.stars)}</td><td class="number neutral">${r.previous_stars==null?'—':number(r.previous_stars)}</td><td class="number ${r.momentum>0?'positive':r.momentum<0?'negative':'neutral'}">${r.momentum==null?'—':(r.momentum>0?'+':'')+number(r.momentum)} ${r.previous_stars===0?'<span class="tag">New attention</span>':''}</td></tr>`).join('');
  $('view').innerHTML=`<div class="panel"><div class="panel-heading"><div><h2>Repositories taking off</h2><p>Momentum = new stars minus the previous equal-length window.</p></div><div class="sort-controls"><button data-sort="momentum" class="${report.effective_sort==='momentum'?'active':''}" ${!report.comparison_available?'disabled':''}>Momentum</button><button data-sort="stars" class="${report.effective_sort==='stars'?'active':''}">New stars</button></div><label class="search"><input id="search" type="search" placeholder="Find a repository" aria-label="Find a repository" value="${escape(state.search)}"></label></div>${!report.comparison_available?'<div class="notice">The full previous window is outside this dataset. Ranking by new stars; comparison is unavailable.</div>':''}<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Repository</th><th class="number">New stars</th><th class="number">Previous</th><th class="number">Change</th></tr></thead><tbody>${rows}</tbody></table>${!rows?'<div class="empty">No star events match this range and repository search.</div>':''}</div></div>`;
  for (const button of document.querySelectorAll('[data-sort]')) button.onclick=()=>{state.sort=button.dataset.sort;load();};
  for (const button of document.querySelectorAll('[data-repo]')) button.onclick=()=>{location.hash=`repo/${button.dataset.repo}`;};
  $('search').oninput=event=>{state.search=event.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>load(),350);};
  if (searching) {$('search').focus();$('search').setSelectionRange(...selection);}
}
function renderRepo(report) {
  if (chart) chart.destroy();
  const pr=report.open_prs, stats=report.merge_stats, url=repoUrl(report.repo_name);
  const prs=pr.items.map(p=>`<tr><td><a href="${url}/pull/${p.number}" target="_blank" rel="noopener">#${p.number}</a><small>${escape(p.action)}</small></td><td>${escape(utc(p.state_at))}<small>First observed opening: ${escape(utc(p.opened_at))}</small></td><td>${escape(p.opened_by || 'Unknown')}</td></tr>`).join('');
  const people=report.contributors.map(p=>`<tr><td><a href="https://github.com/${encodeURIComponent(p.login)}" target="_blank" rel="noopener">${escape(p.login)}</a></td><td class="number total">${number(p.contributions)}</td><td class="number">${number(p.pushes)}</td><td class="number">${number(p.pull_requests)}</td><td class="number">${number(p.issues)}</td><td class="number">${number(p.reviews)}</td><td class="number">${number(p.comments)}</td></tr>`).join('');
  $('view').innerHTML=`<div class="repo-head"><div><a class="back" href="#">Back to trends</a><h2>${escape(report.repo_name)}</h2><p>${escape(utc(report.start))} to ${escape(utc(report.end))}</p></div><a href="${url}" target="_blank" rel="noopener">View on GitHub</a></div><div class="panel chart-panel"><div class="panel-heading"><div><h3>Activity over time</h3><p>${report.activity.grain==='hour'?'Hourly':'Daily'} event counts. Click the legend to show or hide a type. PR events include all PR actions.</p></div></div><div class="chart-container"><canvas id="activity-chart" role="img" aria-label="Repository activity by event type"></canvas></div></div><div class="detail-grid"><div class="panel"><div class="panel-heading"><div><h3>${number(pr.total)} observed open PRs</h3><p>As of ${escape(utc(pr.as_of))}; independent of the activity range.</p></div></div><div class="table-wrap"><table class="pr-table"><thead><tr><th>PR</th><th>Latest state transition</th><th>Opening actor</th></tr></thead><tbody>${prs}</tbody></table>${!prs?'<div class="empty">No open PRs can be established from the observed history.</div>':''}</div><div class="pagination"><span>${pr.total?`${pr.offset+1}–${Math.min(pr.offset+pr.limit,pr.total)} of ${number(pr.total)}`:'0 observed open'}</span><button id="pr-prev" ${pr.offset===0?'disabled':''}>Previous</button><button id="pr-next" ${pr.offset+pr.limit>=pr.total?'disabled':''}>Next</button></div></div><div class="panel"><div class="panel-heading"><div><h3>Time to merge</h3><p>PRs merged within the selected activity range.</p></div></div><div class="stats"><div><span>Median</span><strong>${duration(stats.median_seconds)}</strong></div><div><span>Mean</span><strong>${duration(stats.mean_seconds)}</strong></div><div><span>90th percentile</span><strong>${duration(stats.p90_seconds)}</strong></div></div><div class="explanation"><p class="sample">${number(stats.paired_prs)} measurable of ${number(stats.merged_prs)} merged PRs${stats.coverage==null?'':` (${Math.round(stats.coverage*100)}%)`}</p><p>Measured from the first observed opening to merge. PRs without an opening event have an unknown duration and are excluded.</p></div></div></div><div class="panel"><div class="panel-heading"><div><h3>Top contributors</h3><p>Contribution events: pushes, opened PRs/issues, created reviews and comments. One push is not a commit count.</p></div><label class="bot-toggle"><input id="bots" type="checkbox" ${state.bots?'checked':''}> Include bots</label></div><div class="table-wrap"><table class="contributor-table"><thead><tr><th>Actor</th><th class="number">Events</th><th class="number">Pushes</th><th class="number">PRs opened</th><th class="number">Issues opened</th><th class="number">Reviews</th><th class="number">Comments</th></tr></thead><tbody>${people}</tbody></table>${!people?'<div class="empty">No matching contribution events in this range.</div>':''}</div></div>`;
  $('pr-prev').onclick=()=>{state.offset=Math.max(0,state.offset-25);load();};
  $('pr-next').onclick=()=>{state.offset+=25;load();};
  $('bots').onchange=event=>{state.bots=event.target.checked;load();};
  const keyTypes=new Set(['WatchEvent','PullRequestEvent','IssuesEvent','PullRequestReviewEvent','IssueCommentEvent']);
  chart=new Chart($('activity-chart'),{type:'line',data:{labels:report.activity.buckets.map(t=>new Date(t).toLocaleString('en-GB',{timeZone:'UTC',month:'short',day:'2-digit',...(report.activity.grain==='hour'?{hour:'2-digit',minute:'2-digit'}:{})})),datasets:report.activity.series.map((series,i)=>({label:names[series.type] || series.type,data:series.counts,borderColor:colors[series.type] || ['#78899c','#a8856b','#66865f','#947ba2'][i%4],backgroundColor:colors[series.type] || '#78899c',borderWidth:2,pointRadius:0,pointHitRadius:7,hidden:!keyTypes.has(series.type),borderDash:colors[series.type]?[]:[4,3]}))},options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},plugins:{legend:{position:'bottom',labels:{boxWidth:14,boxHeight:3,font:{size:11}}}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:9,maxRotation:0}},y:{beginAtZero:true,title:{display:true,text:'Events'},ticks:{precision:0}}}}});
}
$('range-form').onsubmit=event=>{event.preventDefault();state.start=$('start').value+'Z';state.end=$('end').value+'Z';state.preset='custom';state.offset=0;setInputs();load();};
for (const button of document.querySelectorAll('[data-preset]')) button.onclick=()=>{if(state.meta?.coverage_start){preset(button.dataset.preset);load();}};
$('refresh').onclick=()=>load(true);
function navigate(){const match=location.hash.match(/^#repo\/(\d+)$/);state.repo=match?Number(match[1]):null;state.offset=0;window.scrollTo(0,0);load();}
window.addEventListener('hashchange',navigate);
navigate();
