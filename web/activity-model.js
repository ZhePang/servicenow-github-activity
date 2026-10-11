/* Domain view models: no DOM or Chart.js dependency. */
(function (root) {
  'use strict';
  /** @typedef {{type: string, counts: number[]}} ActivitySeries */
  /** @typedef {{grain: 'hour'|'day', buckets: string[], series: ActivitySeries[]}} ActivityResponse */
  /** @typedef {{type: string, label: string, counts: number[], total: number, peak: number, core: boolean}} ActivityLane */
  /** @typedef {{status: 'measured'|'missing_openings'|'no_merges', missing: number, coveragePercent: number}} MergeView */
  const labels = {PullRequestEvent:'PR events',IssuesEvent:'Issues',WatchEvent:'Stars',PushEvent:'Pushes',
    PullRequestReviewEvent:'Reviews',IssueCommentEvent:'Issue / PR comments',
    PullRequestReviewCommentEvent:'Inline review comments',CreateEvent:'Branch / tag creation',
    DeleteEvent:'Branch / tag deletion',ForkEvent:'Forks',ReleaseEvent:'Releases'};
  const coreTypes = ['PullRequestEvent','IssuesEvent','WatchEvent','PushEvent','PullRequestReviewEvent','IssueCommentEvent'];
  /** @param {ActivityResponse} activity */
  function buildActivityModel(activity) {
    const buckets = [...activity.buckets];
    const series = new Map(activity.series.map(series => {
      if (series.counts.length !== buckets.length) throw new Error('Event counts must align with time buckets.');
      return [series.type, [...series.counts]];
    }));
    const extraTypes = [...series.keys()].filter(type => !coreTypes.includes(type)).sort();
    const lanes = [...coreTypes, ...extraTypes].map(type => {
      const counts = series.get(type) || buckets.map(() => 0);
      return {type, label: labels[type] || type, counts,
        total: counts.reduce((sum,count) => sum+count,0),
        peak: counts.reduce((peak,count) => Math.max(peak,count),0), core: coreTypes.includes(type)};
    });
    return {grain: activity.grain, buckets, core: lanes.filter(lane => lane.core), extra: lanes.filter(lane => !lane.core),
      total: lanes.reduce((sum,lane) => sum+lane.total,0), maxCount: Math.max(1,...lanes.map(lane => lane.peak))};
  }
  /** @returns {MergeView} */
  function buildMergeView(stats) {
    return {status: stats.paired_prs>0 ? 'measured' : stats.merged_prs>0 ? 'missing_openings' : 'no_merges',
      missing: stats.merged_prs-stats.paired_prs,
      coveragePercent: stats.merged_prs ? Math.round(stats.paired_prs/stats.merged_prs*100) : 0};
  }
  const api = {buildActivityModel, buildMergeView};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ActivityModel = api;
})(typeof window !== 'undefined' ? window : this);
