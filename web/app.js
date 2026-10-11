'use strict';
const $ = id => document.getElementById(id);
const state = {meta:null,start:null,end:null,preset:'7',sort:'momentum',search:'',repo:null,bots:false,offset:0};
let controller, charts=[], searchTimer;
const activityState={shared:false,moreOpen:false};
const number = n => new Intl.NumberFormat('en-US').format(n);
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const utc = value => value ? new Date(value).toLocaleString('en-GB',{timeZone:'UTC',day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) + ' UTC' : 'Unknown';
const repoUrl = name => 'https://github.com/' + name.split('/').map(encodeURIComponent).join('/');
const duration = seconds => seconds == null ? 'Unavailable' : seconds < 60 ? `${seconds.toFixed(1)}s` : seconds < 3600 ? `${(seconds/60).toFixed(1)}m` : seconds < 86400 ? `${(seconds/3600).toFixed(1)}h` : `${(seconds/86400).toFixed(1)}d`;
const inputDate = date => new Date(date).toISOString().slice(0,19);
const colors = {WatchEvent:'#b8860b',PullRequestEvent:'#2563eb',IssuesEvent:'#7c3aed',PushEvent:'#3a7b79',IssueCommentEvent:'#c6674c',PullRequestReviewEvent:'#667ca9',PullRequestReviewCommentEvent:'#99629d',CreateEvent:'#697a91',DeleteEvent:'#ae6878',ForkEvent:'#4c7f9b',ReleaseEvent:'#728344'};

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
  destroyCharts();
  const rows=report.repositories.map((r,i)=>`<tr><td class="rank">${i+1}</td><td class="repo-cell"><button data-repo="${r.repo_id}">${escape(r.repo_name)}</button></td><td class="number">${number(r.stars)}</td><td class="number neutral">${r.previous_stars==null?'—':number(r.previous_stars)}</td><td class="number ${r.momentum>0?'positive':r.momentum<0?'negative':'neutral'}">${r.momentum==null?'—':(r.momentum>0?'+':'')+number(r.momentum)} ${r.previous_stars===0?'<span class="tag">New attention</span>':''}</td></tr>`).join('');
  $('view').innerHTML=`<div class="panel"><div class="panel-heading"><div><h2>Repositories taking off</h2><p>Momentum = new stars minus the previous equal-length window.</p></div><div class="sort-controls"><button data-sort="momentum" class="${report.effective_sort==='momentum'?'active':''}" ${!report.comparison_available?'disabled':''}>Momentum</button><button data-sort="stars" class="${report.effective_sort==='stars'?'active':''}">New stars</button></div><label class="search"><input id="search" type="search" placeholder="Find a repository" aria-label="Find a repository" value="${escape(state.search)}"></label></div>${!report.comparison_available?'<div class="notice">The full previous window is outside this dataset. Ranking by new stars; comparison is unavailable.</div>':''}<div class="table-wrap"><table><thead><tr><th>Rank</th><th>Repository</th><th class="number">New stars</th><th class="number">Previous</th><th class="number">Change</th></tr></thead><tbody>${rows}</tbody></table>${!rows?'<div class="empty">No star events match this range and repository search.</div>':''}</div></div>`;
  for (const button of document.querySelectorAll('[data-sort]')) button.onclick=()=>{state.sort=button.dataset.sort;load();};
  for (const button of document.querySelectorAll('[data-repo]')) button.onclick=()=>{location.hash=`repo/${button.dataset.repo}`;};
  $('search').oninput=event=>{state.search=event.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>load(),350);};
  if (searching) {$('search').focus();$('search').setSelectionRange(...selection);}
}
function destroyCharts() {
  for (const entry of charts) entry.chart.destroy();
  charts=[];
}
function laneColor(type) {
  return colors[type] || '#697a91';
}
function activityPanel(model) {
  const lanes=[...model.core,...model.extra];
  const cards=items=>items.map(lane=>{
    const index=lanes.indexOf(lane);
    return `<article class="activity-lane"><header><h4><span class="type-dot" style="background:${laneColor(lane.type)}"></span>${escape(lane.label)}</h4><span class="lane-total">${number(lane.total)} <small>events</small></span></header><p class="lane-peak">Peak ${number(lane.peak)} / ${model.grain}</p><div class="lane-chart"><canvas id="activity-${index}" role="img" aria-label="${escape(lane.label)} per ${model.grain}: ${number(lane.total)} total events, peak ${number(lane.peak)}"></canvas>${lane.total===0?'<p class="lane-empty">No events in this range</p>':''}</div></article>`;
  }).join('');
  const rows=model.buckets.map((bucket,index)=>`<tr><th scope="row">${escape(utc(bucket))}</th>${lanes.map(lane=>`<td class="number">${number(lane.counts[index])}</td>`).join('')}</tr>`).join('');
  return `<section class="panel chart-panel" aria-labelledby="activity-heading"><div class="panel-heading"><div><h3 id="activity-heading">Activity over time</h3><p>${model.grain==='hour'?'Hourly':'Daily'} counts in UTC. PR events include all PR actions.</p></div><div class="activity-controls"><span class="activity-total">${number(model.total)} events in this range</span><label class="scale-toggle"><input id="shared-scale" type="checkbox" ${activityState.shared?'checked':''} aria-describedby="scale-note"> Use same scale</label></div></div><p id="scale-note" class="scale-note">${activityState.shared?'All charts use the same count scale to compare volumes.':'Each chart has its own count scale to reveal its pattern.'}</p>${model.total===0?'<div class="notice">No activity was observed in this range. Choose a wider range to explore this repository.</div>':''}<div class="activity-grid">${cards(model.core)}</div>${model.extra.length?`<details id="extra-types" class="activity-disclosure" ${activityState.moreOpen?'open':''}><summary>More event types (${model.extra.length})</summary><div class="activity-grid">${cards(model.extra)}</div></details>`:''}<details class="activity-values"><summary>View event counts</summary><p>Exact counts for the selected range. Boundary buckets may be partial.</p><div class="table-wrap"><table><thead><tr><th scope="col">Bucket start (UTC)</th>${lanes.map(lane=>`<th scope="col" class="number">${escape(lane.label)}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div></details></section>`;
}
function mountActivity(model) {
  const labels=model.buckets.map(bucket=>new Date(bucket).toLocaleString('en-GB',{timeZone:'UTC',month:'short',day:'2-digit',...(model.grain==='hour'?{hour:'2-digit',minute:'2-digit'}:{})}));
  [...model.core,...model.extra].forEach((lane,index)=>{
    const chart=new Chart($(`activity-${index}`),{
      type:'bar',
      data:{labels,datasets:[{label:lane.label,data:lane.counts,backgroundColor:laneColor(lane.type),borderRadius:2,maxBarThickness:24,categoryPercentage:.8,barPercentage:.85}]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,
        interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:{displayColors:false,backgroundColor:'#17233b',padding:11,
          callbacks:{title:items=>utc(model.buckets[items[0].dataIndex]),label:context=>`${number(context.parsed.y)} events`}}},
        scales:{x:{grid:{display:false},border:{display:false},ticks:{maxTicksLimit:4,maxRotation:0,color:'#56647b',font:{size:10}}},
          y:{beginAtZero:true,max:activityState.shared?model.maxCount:Math.max(1,lane.peak),border:{display:false},
            grid:{color:'#edf0f5'},ticks:{precision:0,maxTicksLimit:4,color:'#56647b',font:{size:10}}}}
      }
    });
    charts.push({chart,peak:lane.peak});
  });
  $('shared-scale').onchange=event=>{
    activityState.shared=event.target.checked;
    $('scale-note').textContent=activityState.shared?'All charts use the same count scale to compare volumes.':'Each chart has its own count scale to reveal its pattern.';
    for (const entry of charts) {
      entry.chart.options.scales.y.max=activityState.shared?model.maxCount:Math.max(1,entry.peak);
      entry.chart.update('none');
    }
  };
  if ($('extra-types')) $('extra-types').ontoggle=event=>{
    activityState.moreOpen=event.target.open;
    if (event.target.open) for (const entry of charts) entry.chart.resize();
  };
}
function mergePanel(stats) {
  const view=ActivityModel.buildMergeView(stats);
  const sample=`${number(stats.paired_prs)} measurable of ${number(stats.merged_prs)} merged PRs`;
  const coverage=stats.merged_prs?`<div class="timing-coverage"><div><span>${sample}</span><strong>${view.coveragePercent}%</strong></div><div class="coverage-track" role="img" aria-label="${escape(sample)}, ${view.coveragePercent} percent coverage"><span style="width:${view.coveragePercent}%"></span></div></div>`:'';
  const body=view.status==='measured'?`<div class="stats"><div><span>Median</span><strong>${duration(stats.median_seconds)}</strong></div><div><span>Mean</span><strong>${duration(stats.mean_seconds)}</strong></div><div><span>90th percentile</span><strong>${duration(stats.p90_seconds)}</strong></div></div>`:
    `<div class="merge-empty"><h4>${view.status==='missing_openings'?'Opening history is missing':'No PRs merged in this range'}</h4><p>${view.status==='missing_openings'?`${number(stats.merged_prs)} PRs merged, but none has a matching opening event in this snapshot. Their time to merge cannot be calculated.`:'Choose a wider time range to find merged PRs with timing samples.'}</p>${state.preset!=='all'?'<button id="merge-all-data">View full snapshot</button>':''}</div>`;
  return `<section class="panel" data-merge-status="${view.status}" aria-labelledby="merge-heading"><div class="panel-heading"><div><h3 id="merge-heading">Time to merge</h3><p>PRs merged within the selected activity range.</p></div></div>${body}${coverage}<div class="explanation"><p>${view.status==='measured'?`Measured from the first observed opening to merge. ${number(view.missing)} PR${view.missing===1?'':'s'} excluded because opening history is missing.`:'Only PRs with both an observed opening and a merge can be measured.'}</p><p class="source-note">Source: supplied event snapshot</p></div></section>`;
}

function renderRepo(report) {
  const focused=document.activeElement?.id;
  destroyCharts();
  const activity=ActivityModel.buildActivityModel(report.activity);
  const pr=report.open_prs, stats=report.merge_stats, url=repoUrl(report.repo_name);
  const prs=pr.items.map(p=>`<tr><td><a href="${url}/pull/${p.number}" target="_blank" rel="noopener">#${p.number}</a><small>${escape(p.action)}</small></td><td>${escape(utc(p.state_at))}<small>First observed opening: ${escape(utc(p.opened_at))}</small></td><td>${escape(p.opened_by || 'Unknown')}</td></tr>`).join('');
  const people=report.contributors.map(p=>`<tr><td><a href="https://github.com/${encodeURIComponent(p.login)}" target="_blank" rel="noopener">${escape(p.login)}</a></td><td class="number total">${number(p.contributions)}</td><td class="number">${number(p.pushes)}</td><td class="number">${number(p.pull_requests)}</td><td class="number">${number(p.issues)}</td><td class="number">${number(p.reviews)}</td><td class="number">${number(p.comments)}</td></tr>`).join('');
  $('view').innerHTML=`<div class="repo-head"><div><a class="back" href="#">Back to trends</a><h2>${escape(report.repo_name)}</h2><p>${escape(utc(report.start))} to ${escape(utc(report.end))}</p></div><a href="${url}" target="_blank" rel="noopener">View on GitHub</a></div>${activityPanel(activity)}<div class="detail-grid"><div class="panel"><div class="panel-heading"><div><h3>${number(pr.total)} observed open PRs</h3><p>As of ${escape(utc(pr.as_of))}; independent of the activity range.</p></div></div><div class="table-wrap"><table class="pr-table"><thead><tr><th>PR</th><th>Latest state transition</th><th>Opening actor</th></tr></thead><tbody>${prs}</tbody></table>${!prs?'<div class="empty">No open PRs can be established from the observed history.</div>':''}</div><div class="pagination"><span>${pr.total?`${pr.offset+1}–${Math.min(pr.offset+pr.limit,pr.total)} of ${number(pr.total)}`:'0 observed open'}</span><button id="pr-prev" ${pr.offset===0?'disabled':''}>Previous</button><button id="pr-next" ${pr.offset+pr.limit>=pr.total?'disabled':''}>Next</button></div></div>${mergePanel(stats)}</div><div class="panel"><div class="panel-heading"><div><h3>Top contributors</h3><p>Contribution events: pushes, opened PRs/issues, created reviews and comments. One push is not a commit count.</p></div><label class="bot-toggle"><input id="bots" type="checkbox" ${state.bots?'checked':''}> Include bots</label></div><div class="table-wrap"><table class="contributor-table"><thead><tr><th>Actor</th><th class="number">Events</th><th class="number">Pushes</th><th class="number">PRs opened</th><th class="number">Issues opened</th><th class="number">Reviews</th><th class="number">Comments</th></tr></thead><tbody>${people}</tbody></table>${!people?'<div class="empty">No matching contribution events in this range.</div>':''}</div></div>`;
  $('pr-prev').onclick=()=>{state.offset=Math.max(0,state.offset-25);load();};
  $('pr-next').onclick=()=>{state.offset+=25;load();};
  $('bots').onchange=event=>{state.bots=event.target.checked;load();};
  mountActivity(activity);
  if ($('merge-all-data')) $('merge-all-data').onclick=()=>{preset('all');load();};
  if (focused && $(focused)) $(focused).focus({preventScroll:true});
}
$('range-form').onsubmit=event=>{event.preventDefault();state.start=$('start').value+'Z';state.end=$('end').value+'Z';state.preset='custom';state.offset=0;setInputs();load();};
for (const button of document.querySelectorAll('[data-preset]')) button.onclick=()=>{if(state.meta?.coverage_start){preset(button.dataset.preset);load();}};
$('refresh').onclick=()=>load(true);
function navigate(){const match=location.hash.match(/^#repo\/(\d+)$/);state.repo=match?Number(match[1]):null;state.offset=0;window.scrollTo(0,0);load();}
window.addEventListener('hashchange',navigate);
navigate();
