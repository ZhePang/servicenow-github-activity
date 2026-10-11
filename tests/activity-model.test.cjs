const test = require('node:test');
const assert = require('node:assert/strict');
const {buildActivityModel, buildMergeView} = require('../web/activity-model.js');

const buckets = ['2026-08-01T00:00:00Z','2026-08-02T00:00:00Z','2026-08-03T00:00:00Z'];

test('activity lanes preserve counts, align buckets, and expose totals and peaks', () => {
  const input = {grain:'day', buckets, series:[{type:'WatchEvent',counts:[0,2,5]},{type:'PullRequestEvent',counts:[3,0,1]}]};
  const model = buildActivityModel(input);
  assert.deepEqual(model.core.map(l=>l.type), ['PullRequestEvent','IssuesEvent','WatchEvent','PushEvent','PullRequestReviewEvent','IssueCommentEvent']);
  assert.deepEqual(model.core[0].counts,[3,0,1]);
  assert.deepEqual(model.core[1].counts,[0,0,0]);
  assert.equal(model.core[2].total,7);
  assert.equal(model.core[2].peak,5);
  assert.equal(model.total,11);
  assert.equal(model.maxCount,5);
  assert.deepEqual(model.buckets,buckets);
  model.core[0].counts[0]=999;
  assert.equal(input.series[1].counts[0],3);
});

test('additional types remain available with deterministic labels and ordering', () => {
  const model=buildActivityModel({grain:'day',buckets,series:[{type:'FutureEvent',counts:[0,1,0]},{type:'CreateEvent',counts:[0,3,0]}]});
  assert.deepEqual(model.extra.map(l=>l.type),['CreateEvent','FutureEvent']);
  assert.equal(model.extra[1].label,'FutureEvent');
  assert.equal(model.total,4);
});

test('zero activity has a usable scale and a truthful empty marker', () => {
  const model=buildActivityModel({grain:'hour',buckets,series:[]});
  assert.equal(model.total,0);
  assert.equal(model.maxCount,1);
  assert.ok(model.core.every(l=>l.total===0 && l.peak===0));
});

test('rejects a malformed response instead of silently misaligning dates', () => {
  assert.throws(()=>buildActivityModel({grain:'day',buckets,series:[{type:'WatchEvent',counts:[1]}]}),/bucket/i);
});

test('merge view distinguishes no merges from missing opening history', () => {
  assert.deepEqual(buildMergeView({merged_prs:0,paired_prs:0}),{status:'no_merges',missing:0,coveragePercent:0});
  assert.deepEqual(buildMergeView({merged_prs:3,paired_prs:0}),{status:'missing_openings',missing:3,coveragePercent:0});
});

test('valid timing samples including zero duration remain measurable', () => {
  assert.deepEqual(buildMergeView({merged_prs:4,paired_prs:1,median_seconds:0}),{status:'measured',missing:3,coveragePercent:25});
});
