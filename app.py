import streamlit as st
import pandas as pd
import re
import base64
from datetime import datetime
import googleapiclient.discovery
import google.generativeai as genai

# --- [1. 보안 및 API 설정] ---
try:
    YOUTUBE_KEY = st.secrets["YOUTUBE_API_KEY"]
    GEMINI_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("🚨 보안 설정(.streamlit/secrets.toml)을 확인해주세요.")
    st.stop()

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('models/gemini-2.0-flash')
YOUTUBE = googleapiclient.discovery.build('youtube', 'v3', developerKey=YOUTUBE_KEY)

# --- [2. UI 설정 및 로고 고정] ---
st.set_page_config(page_title="유튜브 크리에이터 서치", layout="wide")

def add_logo(logo_path):
    try:
        with open(logo_path, "rb") as f:
            data = f.read()
        encoded = base64.b64encode(data).decode()
        st.markdown(
            f"""
            <style>
            [data-testid="stAppViewContainer"]::before {{
                content: "";
                position: fixed;
                top: 20px;
                right: 30px;
                width: 130px;
                height: 60px;
                background-image: url("data:image/png;base64,{encoded}");
                background-size: contain;
                background-repeat: no-repeat;
                background-position: right top;
                z-index: 1001;
            }}
            </style>
            """,
            unsafe_allow_html=True,
        )
    except FileNotFoundError:
        pass

add_logo("logo.png")

# 메인 타이틀
st.title("🌐 유튜브 크리에이터 서치 웹사이트")
st.markdown("데이터 기반의 고효율 한국인 크리에이터를 자동으로 찾아냅니다.")
st.markdown("---")

# --- [3. 메인 검색 폼 (유저 친화적 개선)] ---
# st.form을 사용하면 텍스트 입력 후 '엔터'를 눌렀을 때 자동으로 검색이 실행됩니다.
with st.form("search_form"):
    # 첫 번째 줄: 검색창과 버튼을 5:1 비율로 배치
    col1, col2 = st.columns([5, 1])
    with col1:
        keywords_input = st.text_input(
            "🔎 검색 키워드", 
            placeholder="애견 카페, 강아지, 고양이 (쉼표로 구분하여 입력)",
            label_visibility="collapsed" # 디자인을 위해 라벨 숨김
        )
    with col2:
        submit_button = st.form_submit_button("🚀 검색")

    # 두 번째 줄: 세부 필터 설정 (3칸으로 나누어 메인 화면에 배치)
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        efficiency_val = st.slider("최소 구독자 대비 조회수 효율 (%)", 0, 100, 30)
        efficiency_target = efficiency_val / 100
    with f_col2:
        min_view_floor = st.number_input("최소 평균 조회수 설정", 0, 500000, 50000, step=5000)
    with f_col3:
        max_res = st.number_input("키워드당 분석 채널 수", 5, 50, 20)

st.markdown("---")

# --- [4. 로직 함수들] ---
def extract_email_ai(desc):
    if not desc or len(desc.strip()) < 5:
        return "설명란 없음"
    prompt = f"다음 텍스트에서 이메일을 추출해줘. 없으면 오직 'None'이라고만 답해: {desc}"
    try:
        response = model.generate_content(prompt)
        res = response.text.strip()
        if "@" in res and len(res) < 50: return res
        return "직접 확인 필요"
    except: return "AI 검색 실패"

def is_korean(text):
    return bool(re.search('[ㄱ-ㅎ|가-힣]+', text))

def check_performance(up_id, subs):
    if subs == 0: return False, 0, 0
    try:
        req = YOUTUBE.playlistItems().list(part="contentDetails", playlistId=up_id, maxResults=15).execute()
        v_ids = [i['contentDetails']['videoId'] for i in req.get('items', [])]
        v_res = YOUTUBE.videos().list(part="statistics,contentDetails", id=",".join(v_ids)).execute()
        longforms = [v for v in v_res['items'] if 'M' in v['contentDetails']['duration'] or 'H' in v['contentDetails']['duration']][:10]
        if not longforms: return False, 0, 0
        avg_v = sum(int(v['statistics'].get('viewCount', 0)) for v in longforms) / len(longforms)
        eff = avg_v / subs
        is_valid = (eff >= efficiency_target) and (avg_v >= min_view_floor)
        return is_valid, avg_v, eff
    except: return False, 0, 0

# --- [5. 실행 프로세스] ---
if submit_button:
    if not keywords_input:
        st.warning("⚠️ 검색어를 입력해주세요.")
        st.stop()
        
    kws = [k.strip() for k in keywords_input.split(",")]
    final_list = []
    
    prog = st.progress(0)
    status_msg = st.empty()
    total = len(kws) * max_res
    curr = 0

    with st.status("🔍 유튜버 데이터 정밀 분석 중...", expanded=True) as status:
        for kw in kws:
            st.write(f"📂 **'{kw}'** 키워드 관련 채널 수집 중...")
            search = YOUTUBE.search().list(q=kw, part="snippet", type="channel", maxResults=max_res, regionCode="KR").execute()
            
            for item in search['items']:
                curr += 1
                prog.progress(min(curr/total, 1.0))
                title = item['snippet']['title']
                desc = item['snippet'].get('description', '')
                status_msg.info(f"⏳ 현재 분석 대상: **{title}**")
                
                if not (is_korean(title) or is_korean(desc)): continue

                try:
                    ch = YOUTUBE.channels().list(part="snippet,statistics,contentDetails", id=item['snippet']['channelId']).execute()['items'][0]
                    subs = int(ch['statistics'].get('subscriberCount', 0))
                    thumb_url = ch['snippet']['thumbnails']['default']['url']
                    
                    is_ok, avg_v, eff = check_performance(ch['contentDetails']['relatedPlaylists']['uploads'], subs)
                    
                    if is_ok:
                        st.write(f"✅ **{title}** (구독자 대비 조회수 효율: {eff*100:.1f}%)")
                        email_reg = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', ch['snippet']['description'])
                        email = email_reg[0] if email_reg else extract_email_ai(ch['snippet']['description'])
                        
                        final_list.append({
                            "채널명": title,
                            "구독자": subs,
                            "최근 10개 평균 조회수": round(avg_v),
                            "조회수 효율": f"{eff*100:.1f}%",
                            "이메일": email,
                            "URL": f"https://youtube.com/channel/{ch['id']}",
                            "프로필": thumb_url,
                        })
                except: continue

        status.update(label="✅ 분석이 모두 완료되었습니다!", state="complete", expanded=False)
        status_msg.empty()

    if final_list:
        df = pd.DataFrame(final_list)
        st.subheader(f"📊 검색 결과 (총 {len(final_list)}개 채널 발견)")
        st.data_editor(
            df,
            column_config={
                "프로필": st.column_config.ImageColumn("프로필", width="small"),
                "URL": st.column_config.LinkColumn("채널 링크", display_text="바로가기"),
                "최근 10개 평균 조회수": st.column_config.NumberColumn(format="%d회")
            },
            use_container_width=True,
            hide_index=True,
            disabled=True
        )
        
        csv = df.to_csv(index=False).encode('utf-8-sig')
        st.download_button(
            "📥 검색 결과 엑셀(CSV) 다운로드", 
            data=csv, 
            file_name=f"Creator_Analysis_{datetime.now().strftime('%m%d_%H%M')}.csv",
            use_container_width=True
        )
    else:
        st.warning("🧐 필터 조건에 맞는 채널을 찾지 못했습니다. 필터 값을 조정한 후 다시 시도해 보세요.")
