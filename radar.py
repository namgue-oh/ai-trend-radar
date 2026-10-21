#!/usr/bin/env python3
"""AI 트렌드 레이더 — Claude·Gemini 스킬/기능 동향 상시 수집기 (표준 라이브러리만 사용).

매일 GitHub Actions에서 실행:
  python radar.py            # 수집 + 기록 + 텔레그램 알림(관심 항목만)
  python radar.py --weekly   # 지난 7일 기록으로 주간 상위 항목 알림(월요일)
  python radar.py --dry-run  # 알림을 보내지 않고 미리보기만 출력

비밀값은 환경변수로만 받는다: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GITHUB_TOKEN(Actions가 자동 제공).
조회 실패는 '실패'로 기록하고 '변화 없음'으로 처리하지 않는다.
"""
import json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
KST = timezone(timedelta(hours=9))
UA = "ai-trend-radar/1.0 (personal research digest)"
NOW = datetime.now(timezone.utc)

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
SINCE = NOW - timedelta(hours=CFG.get("lookback_hours", 30))
STATUS = []  # 출처별 조회 결과


def log(source, ok, note=""):
    STATUS.append({"source": source, "ok": ok, "note": note[:200]})


def fetch(url, headers=None, data=None, timeout=20):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h, data=data)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_json(url, headers=None):
    return json.loads(fetch(url, headers))


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            t = datetime.strptime(s.replace("Z", "+00:00"), fmt)
            return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ---------------- 관련도 ----------------
def relevance(text):
    t = (text or "").lower()
    platform = any(k in t for k in CFG["platform_keywords"])
    themes = [k for k, v in CFG["themes"].items() if any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", t) for w in v["keywords"])]
    work_themes = [k for k in themes if k not in ("workflow", "token_cost")]
    score = (1 if platform else 0) + len(themes) + (1 if work_themes else 0)
    return score, themes, platform


def item(source, title, url, created, metric_name, metric, text="", extra=None):
    score, themes, platform = relevance(f"{title} {text}")
    d = {
        "id": f"{source}:{url}",
        "source": source, "title": (title or "").strip()[:200], "url": url,
        "created": created.isoformat() if isinstance(created, datetime) else created,
        "metric_name": metric_name, "metric": metric,
        "relevance": score, "themes": themes, "platform": platform,
    }
    if extra:
        d.update(extra)
    return d


# ---------------- 수집기 ----------------
def hacker_news():
    out = []
    ts = int(SINCE.timestamp())
    for q in CFG["hn_queries"]:
        url = ("https://hn.algolia.com/api/v1/search_by_date?" +
               urllib.parse.urlencode({"query": q, "tags": "story", "numericFilters": f"created_at_i>{ts}", "hitsPerPage": 50}))
        try:
            for h in fetch_json(url)["hits"]:
                link = h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}"
                out.append(item("HN", h.get("title"), link, parse_time(h.get("created_at")), "points", h.get("points") or 0,
                                extra={"discussion": f"https://news.ycombinator.com/item?id={h['objectID']}", "comments": h.get("num_comments") or 0}))
            log(f"HN:{q}", True)
        except Exception as e:
            log(f"HN:{q}", False, repr(e))
    return out


def reddit():
    """Reddit 공개 엔드포인트를 차례로 시도한다. 2025-11 이후 공식 API는 사전 승인제라
    무인증 .json/RSS만 쓴다. 클라우드 IP 차단·속도 제한이 잦으므로 실패를 기록한다."""
    out = []
    for sub in CFG["reddit_subs"]:
        got, err = False, ""
        for base in ("https://www.reddit.com", "https://old.reddit.com"):
            try:
                d = fetch_json(f"{base}/r/{sub}/top.json?t=day&limit=25")
                for rank, c in enumerate(d["data"]["children"], 1):
                    p = c["data"]
                    out.append(item(f"Reddit r/{sub}", p.get("title"), "https://www.reddit.com" + p.get("permalink", ""),
                                    datetime.fromtimestamp(p.get("created_utc", 0), timezone.utc), "score", p.get("score", 0),
                                    p.get("selftext", "")[:500], extra={"comments": p.get("num_comments", 0), "rank": rank}))
                log(f"Reddit:{sub}", True, base)
                got = True
                break
            except Exception as e:
                err += f"{base}: {e!r} "
            time.sleep(2)
        if not got:
            try:  # 마지막 수단: RSS (점수 없음, 순위만)
                root = ET.fromstring(fetch(f"https://www.reddit.com/r/{sub}/top/.rss?t=day"))
                ns = {"a": "http://www.w3.org/2005/Atom"}
                for rank, e in enumerate(root.findall(".//a:entry", ns), 1):
                    link = e.find("a:link", ns).get("href")
                    out.append(item(f"Reddit r/{sub}", e.findtext("a:title", namespaces=ns), link,
                                    parse_time(e.findtext("a:updated", namespaces=ns)), "rank", rank,
                                    extra={"rank": rank, "score_unknown": True}))
                log(f"Reddit:{sub}", True, "rss")
            except Exception as e2:
                log(f"Reddit:{sub}", False, err + f"| rss {e2!r}")
    return out


def github_trending():
    """github.com/trending 화면(일간·주간)을 읽어 '오늘/이번 주 받은 Stars'를 화제도로 쓴다."""
    out = []
    for since, label in (("daily", "오늘"), ("weekly", "이번 주")):
        try:
            html = fetch(f"https://github.com/trending?since={since}")
            arts = re.findall(r'<article class="Box-row">(.*?)</article>', html, re.S)
            for art in arts:
                m = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', art)
                if not m:
                    continue
                repo = m.group(1).strip()
                dm = re.search(r'<p class="col-9[^"]*">(.*?)</p>', art, re.S)
                desc = re.sub(r"<[^>]+>|\s+", " ", dm.group(1) if dm else "").strip()
                g = re.search(r"([\d,]+)\s+stars\s+(today|this week)", art)
                gained = int(g.group(1).replace(",", "")) if g else 0
                out.append(item("GitHub 트렌딩", repo, f"https://github.com/{repo}", NOW, f"stars {label}", gained, desc,
                                extra={"period": since}))
            log(f"GitHub트렌딩:{since}", bool(arts), "" if arts else "목록 비어 있음(화면 구조 변경 가능)")
        except Exception as e:
            log(f"GitHub트렌딩:{since}", False, repr(e))
    return out


def gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        h["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    return h


def github_new_repos():
    out = []
    since = (NOW - timedelta(days=7)).strftime("%Y-%m-%d")
    for q in CFG["github_search"]:
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": f"{q} created:>={since}", "sort": "stars", "order": "desc", "per_page": 15})
        try:
            for r in fetch_json(url, gh_headers()).get("items", []):
                text = f"{r.get('description') or ''} {' '.join(r.get('topics') or [])}"
                out.append(item("GitHub 신규", r["full_name"], r["html_url"], parse_time(r.get("created_at")), "stars", r.get("stargazers_count", 0), text))
            log(f"GitHub검색:{q}", True)
        except Exception as e:
            log(f"GitHub검색:{q}", False, repr(e))
        time.sleep(2)  # 검색 API 분당 한도 보호
    return out


def github_watch():
    out, stars = [], {}
    for repo in CFG["github_watch"]:
        try:
            meta = fetch_json(f"https://api.github.com/repos/{repo}", gh_headers())
            stars[repo] = meta.get("stargazers_count")
            for rel in fetch_json(f"https://api.github.com/repos/{repo}/releases?per_page=5", gh_headers()):
                t = parse_time(rel.get("published_at"))
                if t and t >= SINCE:
                    it = item("GitHub 릴리스", f"{repo} {rel.get('tag_name')}", rel.get("html_url"), t, "stars", stars[repo], rel.get("body", "")[:800])
                    it["relevance"] = max(it["relevance"], CFG["alert"]["min_relevance"])  # 워치리스트는 관련 항목으로 간주
                    it["watch"] = True
                    out.append(it)
            log(f"GitHub워치:{repo}", True)
        except Exception as e:
            log(f"GitHub워치:{repo}", False, repr(e))
    return out, stars


def rss():
    out = []
    for name, url in CFG["rss"].items():
        try:
            root = ET.fromstring(fetch(url))
            ns = {"a": "http://www.w3.org/2005/Atom"}
            entries = root.findall(".//item") or root.findall(".//a:entry", ns)
            for e in entries:
                title = (e.findtext("title") or e.findtext("a:title", namespaces=ns) or "").strip()
                link_el = e.find("a:link", ns)
                link = e.findtext("link") or (link_el.get("href") if link_el is not None else "")
                t = parse_time(e.findtext("pubDate") or e.findtext("a:published", namespaces=ns) or e.findtext("a:updated", namespaces=ns))
                desc = e.findtext("description") or e.findtext("a:content", namespaces=ns) or e.findtext("a:summary", namespaces=ns) or ""
                if t and t >= SINCE:
                    out.append(item(name, title, link, t, "rss", 0, re.sub(r"<[^>]+>", " ", desc)[:800]))
            log(f"RSS:{name}", True)
        except Exception as e:
            log(f"RSS:{name}", False, repr(e))
    return out


# ---------------- 판정·알림 ----------------
THRESH = {"HN": ("points", "hn_points"), "Reddit": ("score", "reddit_score"),
          "GitHub 신규": ("stars", "github_new_repo_stars"), "GitHub 트렌딩": ("stars", "github_trending_stars")}


def is_hot(it):
    a = CFG["alert"]
    if it["relevance"] < a["min_relevance"]:
        return False
    if it.get("watch"):
        return True
    if not it.get("platform") and not it["source"].startswith("GitHub"):
        return False  # 커뮤니티 글은 Claude·Gemini 언급이 있어야 알림
    if it.get("score_unknown"):
        return it.get("rank", 99) <= a["reddit_rss_top_rank"]
    if it.get("velocity") is not None and it["velocity"] >= a["github_velocity_per_day"]:
        return True
    if it["source"] == "GitHub 트렌딩" and it.get("period") == "weekly":
        return (it["metric"] or 0) >= a["github_trending_week_stars"]
    for prefix, (_, key) in THRESH.items():
        if it["source"].startswith(prefix):
            return (it["metric"] or 0) >= a[key]
    return it["source"] == "Google Workspace Updates" or "releases" in it["source"]


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def fmt_line(it):
    themes = ", ".join(CFG["themes"][t]["label"] for t in it["themes"] if t in CFG["themes"]) or "-"
    m = "공식" if it["metric_name"] == "rss" else (f"오늘 순위 {it['metric']}위(점수 미확인)" if it.get("score_unknown") else f"{it['metric_name']} {it['metric']}")
    if it.get("velocity") is not None:
        m += f" · 하루 +{it['velocity']} stars"
    if it.get("comments"):
        m += f" · 댓글 {it['comments']}"
    return f"• [{it['source']}] {it['title']}\n  {m} · {themes}\n  {it['url']}"


def telegram(text, dry):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    (DATA / "telegram_preview.txt").write_text(text, encoding="utf-8")
    if dry or not tok or not chat:
        print("---- 텔레그램 미리보기 (발송 안 함) ----\n" + text)
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}).encode()
    fetch(f"https://api.telegram.org/bot{tok}/sendMessage", data=body)
    return True


def daily(dry):
    items = []
    items += hacker_news(); items += reddit(); items += github_trending(); items += github_new_repos()
    w, stars = github_watch(); items += w; items += rss()
    # 같은 URL 중복 제거(지표가 큰 쪽 유지)
    uniq = {}
    for it in items:
        k = it["url"]
        if k not in uniq or (it["metric"] or 0) > (uniq[k]["metric"] or 0):
            uniq[k] = it
    items = sorted(uniq.values(), key=lambda x: (x["relevance"], x["metric"] or 0), reverse=True)

    day = NOW.astimezone(KST).strftime("%Y-%m-%d")
    (DATA / "daily").mkdir(parents=True, exist_ok=True)
    hist = load(DATA / "stars.json", {})
    for r, s in stars.items():
        if s is not None:
            hist.setdefault(r, {})[day] = s
    # 화제도: 관련 신규 저장소의 Stars를 매일 기록해 하루 증가 속도를 계산(기록 2일 이상일 때만)
    for it in items:
        if it["source"] == "GitHub 신규" and it["relevance"] >= CFG["alert"]["min_relevance"]:
            repo = it["title"]
            prev = sorted(d for d in hist.get(repo, {}) if d < day)
            hist.setdefault(repo, {})[day] = it["metric"]
            if prev:
                days = max((datetime.fromisoformat(day) - datetime.fromisoformat(prev[-1])).days, 1)
                it["velocity"] = round((it["metric"] - hist[repo][prev[-1]]) / days, 1)
    keep = sorted(hist, key=lambda r: max(hist[r]), reverse=True)[:300]
    hist = {r: hist[r] for r in set(keep) | {r for r in CFG["github_watch"] if r in hist}}
    (DATA / "stars.json").write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")

    seen = set(load(DATA / "seen.json", []))
    hot = [it for it in items if is_hot(it) and it["id"] not in seen][: CFG["alert"]["max_items"]]
    record = {"run_at": NOW.astimezone(KST).isoformat(), "window_start": SINCE.astimezone(KST).isoformat(),
              "status": STATUS, "alerted": [h["id"] for h in hot], "items": [i for i in items if i["relevance"] >= 1]}
    (DATA / "daily" / f"{day}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")

    fails = [s["source"] for s in STATUS if not s["ok"]]
    if hot:
        msg = f"🔎 AI 트렌드 레이더 {day} — 관심 {len(hot)}건\n\n" + "\n\n".join(fmt_line(h) for h in hot)
        if fails:
            msg += f"\n\n조회 실패 {len(fails)}곳: " + ", ".join(fails[:6])
        sent = telegram(msg, dry)
        if sent or dry:
            seen.update(h["id"] for h in hot)
            (DATA / "seen.json").write_text(json.dumps(sorted(seen)[-5000:], ensure_ascii=False), encoding="utf-8")
    print(f"수집 {len(items)}건, 관련(≥1) {len(record['items'])}건, 알림 {len(hot)}건, 실패 {len(fails)}곳: {fails}")


def weekly(dry):
    files = sorted((DATA / "daily").glob("*.json"))[-7:]
    pool, fails = {}, {}
    for f in files:
        d = load(f, {})
        for s in d.get("status", []):
            if not s["ok"]:
                fails[s["source"]] = fails.get(s["source"], 0) + 1
        for it in d.get("items", []):
            if it["relevance"] >= CFG["alert"]["min_relevance"]:
                pool[it["url"]] = it
    top = sorted(pool.values(), key=lambda x: (x["relevance"], x["metric"] or 0), reverse=True)[:7]
    hist = load(DATA / "stars.json", {})
    grow = []
    for r, series in hist.items():
        ds = sorted(series)
        if len(ds) >= 2 and (datetime.fromisoformat(ds[-1]) - datetime.fromisoformat(ds[0])).days >= 6:
            grow.append((series[ds[-1]] - series[ds[0]], r))
    msg = f"📅 AI 트렌드 주간 상위 ({len(files)}일 기록 기준)\n분석 보고는 08:00 Drive 'AI Weekly'와 이메일로 갑니다.\n\n"
    msg += "\n\n".join(fmt_line(t) for t in top) if top else "관련 항목 없음"
    if grow:
        msg += "\n\n워치리스트 Stars 증가(7일): " + ", ".join(f"{r} +{g}" for g, r in sorted(grow, reverse=True)[:5])
    else:
        msg += "\n\nStars 증가율: 기준값 축적 중(7일 이상 기록 필요)"
    if fails:
        msg += "\n조회 실패 누적: " + ", ".join(f"{k}×{v}" for k, v in list(fails.items())[:6])
    telegram(msg, dry)


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    DATA.mkdir(exist_ok=True)
    weekly(dry) if "--weekly" in sys.argv else daily(dry)
