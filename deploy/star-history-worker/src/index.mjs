const GITHUB_API_VERSION = "2026-03-10";
const CACHE_SECONDS = 6 * 60 * 60;
const MAX_HISTORY_PAGES = 100;
const REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return jsonResponse({ ok: true, repository: env.GITHUB_REPOSITORY });
    }

    if ((request.method !== "GET" && request.method !== "HEAD") || !["/", "/card.svg"].includes(url.pathname)) {
      return new Response("Not found", { status: 404 });
    }

    const cache = caches.default;
    const cacheKey = new Request(new URL("/card.svg", request.url).toString(), { method: "GET" });
    const cached = await cache.match(cacheKey);
    if (cached) {
      return request.method === "HEAD" ? headResponse(cached) : cached;
    }

    try {
      const repository = validateRepository(env.GITHUB_REPOSITORY);
      const stats = await fetchRepositoryHistory(repository, env.GITHUB_TOKEN);
      const svg = renderStarHistoryCard({
        ...stats,
        title: env.CARD_TITLE || repository,
      });
      const response = svgResponse(svg);

      ctx.waitUntil(cache.put(cacheKey, response.clone()));
      return request.method === "HEAD" ? headResponse(response) : response;
    } catch (error) {
      console.error(JSON.stringify({
        event: "star_history_render_failed",
        message: error instanceof Error ? error.message : "Unknown error",
      }));

      return svgResponse(renderErrorCard("暂时无法加载 Star 增长数据"), 502, "no-store");
    }
  },
};

export async function fetchRepositoryHistory(repository, token, fetchImpl = fetch) {
  if (!token) {
    throw new Error("GITHUB_TOKEN is not configured");
  }

  const headers = {
    Accept: "application/vnd.github+json",
    Authorization: `Bearer ${token}`,
    "User-Agent": "novelvids-star-history",
    "X-GitHub-Api-Version": GITHUB_API_VERSION,
  };
  const repoUrl = `https://api.github.com/repos/${repository}`;
  const metadataResponse = await fetchImpl(repoUrl, { headers });
  const metadata = await readGitHubJson(metadataResponse, "repository metadata");
  const history = [];

  for (let page = 1; page <= MAX_HISTORY_PAGES; page += 1) {
    const historyResponse = await fetchImpl(
      `${repoUrl}/stargazers/history?per_page=30&page=${page}`,
      { headers },
    );
    const weeks = await readGitHubJson(historyResponse, `star history page ${page}`);

    if (!Array.isArray(weeks)) {
      throw new Error("GitHub returned an invalid star history payload");
    }

    history.push(...weeks);
    if (weeks.length < 30) {
      break;
    }

    if (page === MAX_HISTORY_PAGES) {
      throw new Error("GitHub star history exceeded the supported page limit");
    }
  }

  return {
    repository,
    stars: Number(metadata.stargazers_count) || 0,
    forks: Number(metadata.forks_count) || 0,
    createdAt: metadata.created_at,
    history,
  };
}

async function readGitHubJson(response, label) {
  if (!response.ok) {
    const requestId = response.headers.get("x-github-request-id") || "unknown";
    throw new Error(`GitHub ${label} request failed (${response.status}, request ${requestId})`);
  }

  return response.json();
}

export function renderStarHistoryCard({ repository, title, stars, forks, createdAt, history, now = new Date() }) {
  const width = 920;
  const height = 420;
  const plot = { left: 70, top: 142, right: 38, bottom: 54 };
  const plotWidth = width - plot.left - plot.right;
  const plotHeight = height - plot.top - plot.bottom;
  const daily = normalizeHistory(history);
  const startDate = validDate(createdAt) || daily.at(0)?.date || now;
  const endDate = now > startDate ? now : new Date(startDate.getTime() + 86_400_000);
  const points = buildCumulativePoints(daily, stars, startDate, endDate);
  const yMax = niceCeiling(Math.max(stars, 1));
  const coordinates = points.map((point) => ({
    x: scaleDate(point.date, startDate, endDate, plot.left, plot.left + plotWidth),
    y: plot.top + plotHeight - (point.value / yMax) * plotHeight,
  }));
  const linePath = toLinePath(coordinates);
  const areaPath = `${linePath} L ${formatNumber(plot.left + plotWidth)} ${formatNumber(plot.top + plotHeight)} L ${plot.left} ${formatNumber(plot.top + plotHeight)} Z`;
  const last = coordinates.at(-1) || { x: plot.left, y: plot.top + plotHeight };
  const recentStars = daily
    .filter((item) => item.date >= new Date(endDate.getTime() - 30 * 86_400_000))
    .reduce((total, item) => total + item.count, 0);
  const yTicks = Array.from({ length: 5 }, (_, index) => Math.round((yMax * index) / 4));
  const xTicks = Array.from({ length: 5 }, (_, index) => {
    const ratio = index / 4;
    return new Date(startDate.getTime() + (endDate.getTime() - startDate.getTime()) * ratio);
  });

  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title desc">
  <title id="title">${escapeXml(title)} Star 增长曲线</title>
  <desc id="desc">${escapeXml(repository)} 从 ${formatDate(startDate)} 至 ${formatDate(endDate)} 的 Star 增长，共 ${stars} Stars。</desc>
  <defs>
    <linearGradient id="card-bg" x1="0" y1="0" x2="1" y2="1">
      <stop class="bg-start" offset="0"/>
      <stop class="bg-end" offset="1"/>
    </linearGradient>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop stop-color="#8b7cf6" stop-opacity=".38" offset="0"/>
      <stop stop-color="#57c7ff" stop-opacity=".03" offset="1"/>
    </linearGradient>
    <linearGradient id="line" x1="0" y1="0" x2="1" y2="0">
      <stop stop-color="#8b7cf6" offset="0"/>
      <stop stop-color="#57c7ff" offset=".58"/>
      <stop stop-color="#ff9d91" offset="1"/>
    </linearGradient>
    <filter id="glow" x="-30%" y="-30%" width="160%" height="160%">
      <feGaussianBlur stdDeviation="4" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <clipPath id="card-clip"><rect width="${width}" height="${height}" rx="24"/></clipPath>
  </defs>
  <style>
    .bg-start{stop-color:#fbfbff}.bg-end{stop-color:#f2f5ff}.border{stroke:#dfe3f2}.grid{stroke:#dfe3ee}.primary{fill:#17203a}.muted{fill:#68708a}.pill{fill:#ebeefe}.pill-text{fill:#6255c7}
    text{font-family:Manrope,-apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif}
    @media (prefers-color-scheme:dark){.bg-start{stop-color:#111528}.bg-end{stop-color:#171c34}.border{stroke:#2a3150}.grid{stroke:#2b3250}.primary{fill:#f6f7ff}.muted{fill:#a7afc9}.pill{fill:#262d4e}.pill-text{fill:#c4bcff}}
  </style>
  <g clip-path="url(#card-clip)">
    <rect width="${width}" height="${height}" fill="url(#card-bg)"/>
    <circle cx="820" cy="-28" r="154" fill="#8b7cf6" opacity=".08"/>
    <circle cx="52" cy="430" r="136" fill="#57c7ff" opacity=".07"/>
  </g>
  <rect class="border" x=".5" y=".5" width="${width - 1}" height="${height - 1}" rx="23.5" fill="none"/>
  <g>
    <circle cx="46" cy="46" r="17" fill="#8b7cf6" opacity=".16"/>
    <path d="M46 34.5l3.55 7.2 7.95 1.15-5.75 5.6 1.36 7.9L46 52.62l-7.11 3.73 1.36-7.9-5.75-5.6 7.95-1.15z" fill="#8b7cf6"/>
    <text class="primary" x="75" y="45" font-size="19" font-weight="700">${escapeXml(title)}</text>
    <text class="muted" x="75" y="68" font-size="13">${escapeXml(repository)} · STAR HISTORY</text>
  </g>
  <g>
    <text class="primary" x="806" y="48" font-size="34" font-weight="700">${formatCompact(stars)}</text>
    <text class="muted" x="806" y="69" font-size="13" font-weight="600">TOTAL STARS</text>
  </g>
  <g>
    <rect class="pill" x="70" y="94" width="128" height="30" rx="15"/>
    <text class="pill-text" x="84" y="114" font-size="12.5" font-weight="700">近 30 天 +${recentStars}</text>
    <rect class="pill" x="208" y="94" width="116" height="30" rx="15"/>
    <text class="pill-text" x="222" y="114" font-size="12.5" font-weight="700">Forks ${formatCompact(forks)}</text>
  </g>
  ${yTicks.map((tick) => {
    const y = plot.top + plotHeight - (tick / yMax) * plotHeight;
    return `<line class="grid" x1="${plot.left}" y1="${formatNumber(y)}" x2="${plot.left + plotWidth}" y2="${formatNumber(y)}" opacity=".62" stroke-dasharray="3 7"/><text class="muted" x="${plot.left - 14}" y="${formatNumber(y + 4)}" text-anchor="end" font-size="11">${formatCompact(tick)}</text>`;
  }).join("")}
  <path d="${areaPath}" fill="url(#area)"/>
  <path d="${linePath}" fill="none" stroke="url(#line)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="${formatNumber(last.x)}" cy="${formatNumber(last.y)}" r="6" fill="#ff9d91" stroke="#fff" stroke-width="3" filter="url(#glow)"/>
  ${xTicks.map((tick, index) => {
    const x = plot.left + (plotWidth * index) / 4;
    const anchor = index === 0 ? "start" : index === 4 ? "start" : "middle";
    const adjustedX = index === 4 ? x - 44 : x;
    return `<text class="muted" x="${formatNumber(adjustedX)}" y="${height - 25}" text-anchor="${anchor}" font-size="11.5">${formatMonth(tick)}</text>`;
  }).join("")}
</svg>`;
}

export function normalizeHistory(history) {
  const totals = new Map();

  for (const week of Array.isArray(history) ? history : []) {
    const weekStart = Number(week.week) * 1000;
    const days = Array.isArray(week.days) ? week.days : [];
    days.forEach((value, dayIndex) => {
      const count = Number(value) || 0;
      if (count <= 0 || !Number.isFinite(weekStart)) return;
      const date = new Date(weekStart + dayIndex * 86_400_000);
      const key = date.toISOString().slice(0, 10);
      totals.set(key, (totals.get(key) || 0) + count);
    });
  }

  return [...totals.entries()]
    .map(([date, count]) => ({ date: new Date(`${date}T12:00:00.000Z`), count }))
    .sort((left, right) => left.date - right.date);
}

export function buildCumulativePoints(daily, currentStars, startDate, endDate) {
  const rawTotal = daily.reduce((total, item) => total + item.count, 0);
  let running = 0;
  const points = [{ date: startDate, value: 0 }];

  for (const item of daily) {
    if (item.date < startDate || item.date > endDate) continue;
    running += item.count;
    points.push({
      date: item.date,
      value: rawTotal > 0 ? Math.round((running / rawTotal) * currentStars) : 0,
    });
  }

  points.push({ date: endDate, value: currentStars });
  return points;
}

export function validateRepository(repository) {
  if (typeof repository !== "string" || !REPOSITORY_PATTERN.test(repository)) {
    throw new Error("GITHUB_REPOSITORY must use the owner/repository format");
  }
  return repository;
}

function svgResponse(svg, status = 200, cacheControl = `public, max-age=3600, s-maxage=${CACHE_SECONDS}, stale-while-revalidate=86400`) {
  return new Response(svg, {
    status,
    headers: {
      "Content-Type": "image/svg+xml; charset=utf-8",
      "Cache-Control": cacheControl,
      "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function headResponse(response) {
  return new Response(null, {
    status: response.status,
    statusText: response.statusText,
    headers: response.headers,
  });
}

function jsonResponse(value) {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function renderErrorCard(message) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="920" height="160" viewBox="0 0 920 160" role="img"><rect width="920" height="160" rx="24" fill="#151a2f"/><circle cx="56" cy="80" r="22" fill="#ff9d91" opacity=".16"/><path d="M56 66v17M56 94v1" stroke="#ff9d91" stroke-width="4" stroke-linecap="round"/><text x="94" y="76" fill="#f6f7ff" font-family="system-ui,sans-serif" font-size="18" font-weight="700">${escapeXml(message)}</text><text x="94" y="101" fill="#a7afc9" font-family="system-ui,sans-serif" font-size="13">请检查 Worker 日志与 GITHUB_TOKEN 配置</text></svg>`;
}

function validDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function scaleDate(date, start, end, min, max) {
  const duration = Math.max(end - start, 1);
  return min + ((date - start) / duration) * (max - min);
}

function niceCeiling(value) {
  const magnitude = 10 ** Math.max(Math.floor(Math.log10(value)) - 1, 0);
  const step = 5 * magnitude;
  return Math.max(step, Math.ceil((value * 1.08) / step) * step);
}

function toLinePath(points) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"} ${formatNumber(point.x)} ${formatNumber(point.y)}`).join(" ");
}

function formatNumber(value) {
  return Number(value.toFixed(2));
}

function formatCompact(value) {
  return new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatDate(date) {
  return new Intl.DateTimeFormat("zh-CN", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }).format(date);
}

function formatMonth(date) {
  return new Intl.DateTimeFormat("zh-CN", { year: "2-digit", month: "short", timeZone: "UTC" }).format(date);
}

function escapeXml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}
