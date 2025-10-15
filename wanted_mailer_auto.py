import requests, smtplib, json, os, time
from datetime import datetime, timezone, timedelta
from email.mime_text import MIMEText

CONFIG_FILE = "config.json"
LAST_ID_FILE = "last_id.txt"
BASE_URL = "https://www.wanted.co.kr/api/v4/jobs?country=kr&limit=100&job_sort=job.latest_order"

MY_EMAIL = os.environ.get("MY_EMAIL")
MY_PASSWORD = os.environ.get("MY_PASSWORD")

# ===== 설정 로드 =====
def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ===== 전체 페이지 순회 =====
def fetch_all_jobs(max_pages=20):
    all_jobs = []
    offset = 0
    while True:
        url = f"{BASE_URL}&offset={offset}"
        res = requests.get(url)
        if res.status_code != 200:
            print(f"⚠️ 요청 실패: {res.status_code}")
            break
        data = res.json()
        jobs = data.get("data", [])
        if not jobs:
            break
        all_jobs.extend(jobs)
        print(f"📦 {len(all_jobs)}개 로드 중...")
        if len(jobs) < 100 or offset >= max_pages * 100:
            break
        offset += 100
        time.sleep(0.5)
    print(f"✅ 총 {len(all_jobs)}개 공고 로드 완료")
    return all_jobs

# ===== 필터링 =====
def filter_jobs(jobs, conf):
    filtered = []
    for j in jobs:
        loc = j.get("address", {}).get("full_location", "")
        pos = j.get("position", "").lower()
        yrs = j.get("annual_from", 0) or 0
        if any(r in loc for r in conf["locations"]) and \
           any(k.lower() in pos for k in conf["jobs"]) and \
           yrs >= conf["years"]:
            filtered.append(j)
    return filtered

# ===== 마지막 발송 공고 추적 =====
def get_last_id():
    if not os.path.exists(LAST_ID_FILE):
        return None
    with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
        first = f.readline().strip()
        return first if first else None

def save_last_id_and_log(latest_id, sent_jobs):
    """
    last_id.txt 포맷:
    1줄: 최신ID
    이후: 전송 로그 누적 (가장 최신 로그가 위로 오도록)
    """
    prev_logs = ""
    if os.path.exists(LAST_ID_FILE):
        with open(LAST_ID_FILE, "r", encoding="utf-8") as f:
            _ = f.readline()  # 기존 최신ID 한 줄 건너뛰기
            prev_logs = f.read()

    kst = timezone(timedelta(hours=9))
    ts = datetime.now(kst).strftime('%Y-%m-%d %H:%M:%S KST')

    # 이번 실행 로그(최신 로그가 위에 오도록 이전 로그 앞에 붙임)
    block_lines = [f"--- {ts} sent {len(sent_jobs)} job(s) ---\n"]
    for j in sent_jobs:
        block_lines.append(
            f"[{j['id']}] {j['company']['name']} - {j['position']} | "
            f"{j['address'].get('full_location','')} | "
            f"https://www.wanted.co.kr/wd/{j['id']}\n"
        )
    block_lines.append("\n")
    new_logs = "".join(block_lines) + (prev_logs or "")

    with open(LAST_ID_FILE, "w", encoding="utf-8") as f:
        f.write(str(latest_id) + "\n\n" + new_logs)

# ===== 메일 빌드 =====
def build_email(jobs):
    kst = timezone(timedelta(hours=9))
    dt = datetime.now(kst)
    html = f"<h2>📢 {dt.strftime('%m월 %d일')} 새 채용공고 ({len(jobs)}건)</h2><hr>"
    for j in jobs:
        html += f"""
        <div style='margin-bottom:15px;'>
            <b>{j['company']['name']}</b> - {j['position']}<br>
            📍 {j['address'].get('full_location','')}<br>
            💰 리워드: {j.get('reward', {}).get('formatted_total', 'N/A')}<br>
            <a href='https://www.wanted.co.kr/wd/{j['id']}' target='_blank'>공고 보기</a>
        </div>
        """
    return html

# ===== 메일 전송 =====
def send_mail(to_email, content):
    msg = MIMEText(content, "html")
    kst = timezone(timedelta(hours=9))
    msg["Subject"] = f"[원티드 알림] {datetime.now(kst).strftime('%m월 %d일')} 새 공고 업데이트"
    msg["From"] = MY_EMAIL
    msg["To"] = to_email
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(MY_EMAIL, MY_PASSWORD)
        smtp.send_message(msg)
        print(f"✅ 메일 발송 완료 → {to_email}")

# ===== 실행 =====
if __name__ == "__main__":
    conf = load_config()
    print(f"🎯 조건: 지역={conf['locations']} | 직무={conf['jobs']} | 경력≥{conf['years']}년")

    all_jobs = fetch_all_jobs(max_pages=30)
    jobs = filter_jobs(all_jobs, conf)
    if not jobs:
        print("❌ 조건에 맞는 공고 없음")
        exit()

    last_id = get_last_id()
    latest_id = str(jobs[0]["id"])

    # 새 공고 판단
    if last_id == latest_id:
        print("📭 새 공고 없음 — 메일 생략")
        exit()

    new_jobs = []
    for job in jobs:
        if str(job["id"]) == last_id:
            break
        new_jobs.append(job)

    if new_jobs:
        html = build_email(new_jobs)
        send_mail(conf["email"], html)
        # ✅ 최신 ID 저장 + 이번에 보낸 목록을 last_id.txt에 로그로 남김
        save_last_id_and_log(latest_id, new_jobs)
    else:
        print("📭 새 공고 없음")
