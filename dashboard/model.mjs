export const DAY = 86400000;
export const finite = value => typeof value === 'number' && Number.isFinite(value);
export const percent = value => finite(value) ? `${value > 0 ? '+' : ''}${value.toLocaleString('ko-KR', {minimumFractionDigits:2, maximumFractionDigits:2})}%` : '—';
export const pp = value => finite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(2)}%p` : '비교 기록 없음';
export const dayTime = value => Date.parse(value + 'T00:00:00Z');
export function filterEtfs(etfs, {country = 'all', query = '', eligibleOnly = true, sort = 'cagr', latestDate} = {}) {
  const needle = query.trim().toLocaleLowerCase();
  return etfs.filter(row => (country === 'all' || row.country === country)
    && (!eligibleOnly || (row.eligible && row.last_observed_date === latestDate))
    && `${row.name} ${row.ticker} ${row.investment_area}`.toLocaleLowerCase().includes(needle))
    .sort((a,b) => sort === 'name' ? a.name.localeCompare(b.name, 'ko')
      : ((finite(b.cagr) ? b.cagr : -Infinity) - (finite(a.cagr) ? a.cagr : -Infinity)) || a.id.localeCompare(b.id));
}
export function mergeShards(shards) {
  const dates = new Set(), series = new Map();
  for (const shard of shards) {
    if (shard.schema_version !== 1) throw new Error('지원하지 않는 데이터 형식입니다.');
    shard.dates.forEach(day => dates.add(day));
    for (const [id, points] of Object.entries(shard.series)) {
      if (points.length !== shard.dates.length) throw new Error('날짜와 관측값 수가 일치하지 않습니다.');
      if (!series.has(id)) series.set(id, new Map());
      points.forEach((point, i) => series.get(id).set(shard.dates[i], point));
    }
  }
  return {dates: [...dates].sort(), series};
}
export function pointsFor(history, id, start, end, eligibleOnly = true) {
  const series = history.series.get(id);
  return history.dates.filter(date => date >= start && date <= end).map(date => {
    const p = series?.get(date);
    return {date, cagr: p && (!eligibleOnly || p[3]) && finite(p[0]) ? p[0] : null,
      actualDate: p?.[1] ?? null, status: p?.[2] ?? 'not_collected', eligible: p?.[3] ?? false};
  });
}
export function segments(points) {
  const result = []; let segment = [];
  for (const point of points) {
    if (!finite(point.cagr)) {if (segment.length) result.push(segment); segment = []; continue;}
    if (segment.length && dayTime(point.date) - dayTime(segment.at(-1).date) > DAY) {result.push(segment); segment = [];}
    segment.push(point);
  }
  if (segment.length) result.push(segment);
  return result;
}
export function rangeFor(dates, period = 'all') {
  if (!dates.length) return ['', ''];
  const last = dates.at(-1);
  const start = period === 'all' ? dates[0] : new Date(dayTime(last) - (Number(period) - 1) * DAY).toISOString().slice(0,10);
  return [start < dates[0] ? dates[0] : start, last];
}
export function csvFor(rows, series) {
  const safe = value => {
    let text = String(value ?? '');
    if (/^[=+@\-\t\r]/.test(text) && typeof value !== 'number') text = "'" + text;
    return `"${text.replaceAll('"','""')}"`;
  };
  const data = [['수집일(KST)','국가','티커','종목명','연환산수익률(%)','실제시세기준일','자료상태','이력1년이상']];
  for (const row of rows) for (const p of series(row.id)) data.push([p.date,row.country,row.ticker,row.name,p.cagr,p.actualDate,p.status,p.eligible]);
  return '\ufeff' + data.map(row => row.map(safe).join(',')).join('\r\n');
}
