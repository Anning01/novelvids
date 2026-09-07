import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCumulativePoints,
  fetchRepositoryHistory,
  normalizeHistory,
  renderStarHistoryCard,
  validateRepository,
} from "../src/index.mjs";

test("normalizes weekly history into chronological daily totals", () => {
  const daily = normalizeHistory([
    { week: 1_757_894_400, total: 3, days: [0, 2, 0, 1, 0, 0, 0] },
    { week: 1_757_289_600, total: 1, days: [1, 0, 0, 0, 0, 0, 0] },
  ]);

  assert.equal(daily.length, 3);
  assert.deepEqual(daily.map((item) => item.count), [1, 2, 1]);
  assert.ok(daily[0].date < daily[1].date);
});

test("cumulative points end at the current star count", () => {
  const start = new Date("2026-01-01T00:00:00Z");
  const end = new Date("2026-02-01T00:00:00Z");
  const points = buildCumulativePoints([
    { date: new Date("2026-01-10T00:00:00Z"), count: 2 },
    { date: new Date("2026-01-20T00:00:00Z"), count: 3 },
  ], 10, start, end);

  assert.deepEqual(points.map((point) => point.value), [0, 4, 10, 10]);
});

test("renders an accessible responsive-theme SVG card", () => {
  const svg = renderStarHistoryCard({
    repository: "Anning01/novelvids",
    title: "猫影短剧",
    stars: 296,
    forks: 80,
    createdAt: "2026-02-03T14:41:15Z",
    history: [{ week: 1_770_336_000, total: 4, days: [1, 0, 2, 0, 1, 0, 0] }],
    now: new Date("2026-09-07T00:00:00Z"),
  });

  assert.match(svg, /<title id="title">猫影短剧 Star 增长曲线<\/title>/);
  assert.match(svg, /prefers-color-scheme:dark/);
  assert.match(svg, /296/);
  assert.match(svg, /Anning01\/novelvids/);
  assert.doesNotMatch(svg, /NaN/);
});

test("fetches metadata and all available history pages without leaking the token", async () => {
  const requests = [];
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    if (url.endsWith("/novelvids")) {
      return json({ stargazers_count: 296, forks_count: 80, created_at: "2026-02-03T14:41:15Z" });
    }
    return json([{ week: 1_770_336_000, total: 1, days: [1, 0, 0, 0, 0, 0, 0] }]);
  };

  const result = await fetchRepositoryHistory("Anning01/novelvids", "secret-token", fetchImpl);

  assert.equal(result.stars, 296);
  assert.equal(requests.length, 2);
  assert.equal(requests[0].init.headers.Authorization, "Bearer secret-token");
  assert.ok(requests.every((request) => !request.url.includes("secret-token")));
});

test("continues through full GitHub history pages", async () => {
  const historyPage = Array.from({ length: 30 }, (_, index) => ({
    week: 1_700_000_000 + index * 604_800,
    total: 1,
    days: [1, 0, 0, 0, 0, 0, 0],
  }));
  const fetchImpl = async (url) => {
    if (url.endsWith("/novelvids")) {
      return json({ stargazers_count: 31, forks_count: 4, created_at: "2023-01-01T00:00:00Z" });
    }
    return url.includes("page=1") ? json(historyPage) : json([historyPage[0]]);
  };

  const result = await fetchRepositoryHistory("Anning01/novelvids", "secret-token", fetchImpl);

  assert.equal(result.history.length, 31);
});

test("rejects malformed repository names", () => {
  assert.throws(() => validateRepository("owner/repo/extra"), /owner\/repository/);
});

function json(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
