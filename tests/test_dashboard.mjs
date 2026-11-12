import test from 'node:test';
import assert from 'node:assert/strict';
import {filterEtfs,mergeShards,pointsFor,segments,rangeFor,csvFor,percent} from '../dashboard/model.mjs';

test('country/search filters and ranking preserve identity and unavailable values',()=>{
  const etfs=[
    {id:'US:ABC',ticker:'ABC',name:'Technology',country:'US',cagr:12.345,eligible:true,last_observed_date:'2026-11-12'},
    {id:'KR:ABC',ticker:'ABC',name:'한국 기술',country:'KR',cagr:25,eligible:true,last_observed_date:'2026-11-12'},
    {id:'US:NO',ticker:'NO',name:'Missing',country:'US',cagr:null,eligible:false,last_observed_date:'2026-11-12'},
    {id:'US:OLD',ticker:'OLD',name:'Old',country:'US',cagr:99,eligible:true,last_observed_date:'2026-11-10'}];
  assert.deepEqual(filterEtfs(etfs,{latestDate:'2026-11-12'}).map(r=>r.id),['KR:ABC','US:ABC']);
  assert.deepEqual(filterEtfs(etfs,{latestDate:'2026-11-12',country:'US',query:'abc'}).map(r=>r.id),['US:ABC']);
  assert.deepEqual(filterEtfs(etfs,{latestDate:'2026-11-12',query:'한국'}).map(r=>r.id),['KR:ABC']);
  assert.equal(filterEtfs(etfs,{eligibleOnly:false}).at(-1).cagr,null);
});
test('missing and unavailable observations remain gaps, never zeros or carried prices',()=>{
  const history=mergeShards([{schema_version:1,dates:['2026-11-10','2026-11-11','2026-11-12'],series:{'US:X':[[12,'2026-11-09','latest_available',true],null,[null,null,'unavailable',false]]}}]);
  const points=pointsFor(history,'US:X','2026-11-10','2026-11-12');
  assert.equal(points[0].actualDate,'2026-11-09');
  assert.equal(points[1].cagr,null);
  assert.equal(points[2].cagr,null);
  assert.equal(points[1].status,'not_collected');
});
test('chart segments break at unavailable observations and missing calendar days',()=>{
  const points=[{date:'2026-11-01',cagr:10},{date:'2026-11-02',cagr:11},{date:'2026-11-03',cagr:null},{date:'2026-11-04',cagr:9},{date:'2026-11-07',cagr:12}];
  assert.deepEqual(segments(points).map(s=>s.length),[2,1,1]);
  assert.equal(segments([{date:'2026-11-01',cagr:0}])[0][0].cagr,0);
});
test('monthly shards preserve all dates and enforce aligned lengths',()=>{
  const history=mergeShards([{schema_version:1,dates:['2026-12-01'],series:{X:[[5,'2026-11-30','market_close',true]]}},{schema_version:1,dates:['2026-11-30'],series:{X:[[4,'2026-11-29','market_close',true]]}}]);
  assert.deepEqual(history.dates,['2026-11-30','2026-12-01']);
  assert.equal(pointsFor(history,'X','2026-11-30','2026-12-01')[1].cagr,5);
  assert.throws(()=>mergeShards([{schema_version:1,dates:['2026-11-01'],series:{X:[]}}]));
});
test('eligibility can be disabled to inspect the complete inventory',()=>{
  const history=mergeShards([{schema_version:1,dates:['2026-11-12'],series:{X:[[110,'2026-11-11','market_close',false]]}}]);
  assert.equal(pointsFor(history,'X','2026-11-01','2026-11-30')[0].cagr,null);
  assert.equal(pointsFor(history,'X','2026-11-01','2026-11-30',false)[0].cagr,110);
});
test('date ranges anchor on last saved date and keep one-day observations',()=>{
  assert.deepEqual(rangeFor(['2026-10-01','2026-11-12'],'30'),['2026-10-14','2026-11-12']);
  assert.deepEqual(rangeFor(['2026-11-12'],'all'),['2026-11-12','2026-11-12']);
  assert.deepEqual(rangeFor([]),['','']);
});
test('CSV preserves unrounded data and escapes spreadsheet formulas and commas',()=>{
  const csv=csvFor([{id:'X',country:'US',ticker:'X',name:'=HYPERLINK("bad"),x'}],()=>[{date:'2026-11-12',cagr:12.3456789012345,actualDate:'2026-11-10',status:'latest_available',eligible:true}]);
  assert.ok(csv.startsWith('\ufeff'));
  assert.ok(csv.includes('12.3456789012345'));
  assert.ok(csv.includes('"\'=HYPERLINK(""bad""),x"'));
  assert.equal(percent(null),'—');
  assert.equal(percent(0),'0.00%');
});
