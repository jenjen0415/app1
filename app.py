import os
import io
import uuid
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import streamlit as st
import qrcode

st.set_page_config(page_title="장보기 알림메모", page_icon="🛒", layout="centered", initial_sidebar_state="collapsed")
DB = Path(__file__).resolve().parent / "shopping.sqlite3"
CATEGORIES = ["🥬 야채", "🍎 과일", "🥩 정육·계란", "🐟 수산", "🥛 유제품", "🍚 식품·간식", "🧻 생활용품", "📦 기타"]
PRIORITIES = {1: "1 · 꼭 필요", 2: "2 · 가격 보고", 3: "3 · 저렴할 때"}


def connection():
    con = sqlite3.connect(str(DB), timeout=20)
    con.row_factory = sqlite3.Row
    return con


with connection() as con:
    con.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT, book TEXT NOT NULL,
        category TEXT NOT NULL, name TEXT NOT NULL, priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 3),
        ceiling INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'todo',
        price INTEGER NOT NULL DEFAULT 0, quantity REAL NOT NULL DEFAULT 0,
        total INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
    con.execute("CREATE INDEX IF NOT EXISTS book_index ON items(book)")

# QR에는 추측하기 어려운 메모 식별자만 담습니다. 로그인/접근제어를 대신하지는 않습니다.
raw = st.query_params.get("memo", "")
try:
    book = str(uuid.UUID(raw))
except (ValueError, TypeError, AttributeError):
    book = str(uuid.uuid4())
    st.query_params["memo"] = book


def rows():
    with connection() as con:
        return [dict(r) for r in con.execute("SELECT * FROM items WHERE book=? ORDER BY priority,id", (book,))]


def change(sql, params):
    with connection() as con:
        con.execute(sql, params)


def money(value):
    return f"{value:,.0f}원"


def flash(message):
    st.session_state["notice"] = message
    st.rerun()


@st.dialog("➕ 살 물건 추가")
def add_item():
    with st.form("add_form", clear_on_submit=True):
        category = st.selectbox("카테고리", CATEGORIES)
        name = st.text_input("상품명", max_chars=60, placeholder="예: 방울토마토 한 팩")
        priority = st.selectbox("중요도", list(PRIORITIES), format_func=lambda v: PRIORITIES[v], index=1)
        ceiling = st.number_input("단위당 희망 최대가격 (원, 0=미설정)", min_value=0, max_value=100000000, step=100)
        st.caption("중요도 2·3은 비싸면 보류하세요. 가격은 구매를 막지 않는 참고 기준입니다.")
        submitted = st.form_submit_button("메모에 추가", type="primary", use_container_width=True)
    if submitted:
        if not name.strip():
            st.warning("상품명을 적어 주세요.")
        else:
            change("INSERT INTO items(book,category,name,priority,ceiling) VALUES(?,?,?,?,?)", (book, category, name.strip(), priority, int(ceiling)))
            flash("메모에 추가했어요.")


@st.dialog("🛒 카트에 담기")
def purchase(item):
    st.write(f"**{item['name']}** · {PRIORITIES[item['priority']]}")
    if item['ceiling']:
        st.caption(f"희망 최대가격: 단위당 {money(item['ceiling'])}")
    # 폼 밖의 입력을 사용해 입력할 때마다 예상 합계를 즉시 갱신합니다.
    price = st.number_input("단가 (원) · 할인 적용 후 가격", min_value=0, max_value=100000000, value=0, step=100, key=f"price_{item['id']}")
    quantity = st.number_input("수량 (개·팩·kg 등 단가와 같은 단위)", min_value=0.01, max_value=100000.0, value=1.0, step=1.0, format="%.2f", key=f"qty_{item['id']}")
    total = int((Decimal(str(price)) * Decimal(str(quantity))).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
    st.write(f"이번 상품 합계 **{money(total)}**")
    if item['ceiling'] and price > item['ceiling']:
        st.warning("희망가격보다 비싸요. 꼭 필요하지 않다면 보류해도 괜찮아요.")
    a, b = st.columns(2)
    if a.button("담기 확정", type="primary", use_container_width=True):
        change("UPDATE items SET status='cart',price=?,quantity=?,total=? WHERE id=? AND book=? AND status='todo'", (int(price), float(quantity), total, item['id'], book))
        flash("카트에 담았어요. 메모에서 빠지고 총액에 반영됐어요.")
    if b.button("이번엔 보류", use_container_width=True):
        change("UPDATE items SET status='hold' WHERE id=? AND book=? AND status='todo'", (item['id'], book))
        flash("보류했어요. 총액에는 포함하지 않아요.")


@st.dialog("카트 상품 관리")
def manage_cart(item):
    st.write(f"**{item['name']}**")
    st.write(f"{money(item['price'])} × {item['quantity']:g} = **{money(item['total'])}**")
    st.caption("수량·가격을 바꾸려면 메모로 되돌린 뒤 다시 담아 주세요.")
    if st.button("↩ 메모로 되돌리기", use_container_width=True):
        change("UPDATE items SET status='todo',price=0,quantity=0,total=0 WHERE id=? AND book=?", (item['id'], book))
        flash("메모로 되돌리고 카트 합계에서 제외했어요.")


@st.dialog("메모 정리")
def manage_item(item):
    st.write(f"**{item['name']}**")
    if item['status'] == 'hold':
        if st.button("↩ 살 목록으로 복귀", use_container_width=True):
            change("UPDATE items SET status='todo' WHERE id=? AND book=?", (item['id'], book))
            flash("살 목록으로 복귀했어요.")
    elif st.button("⏸ 이번엔 보류", use_container_width=True):
        change("UPDATE items SET status='hold' WHERE id=? AND book=?", (item['id'], book))
        flash("보류했어요.")
    if st.button("메모 삭제 (미구매 상품)", use_container_width=True):
        change("DELETE FROM items WHERE id=? AND book=? AND status!='cart'", (item['id'], book))
        flash("미구매 메모를 삭제했어요.")


@st.dialog("📱 QR로 이 메모 열기")
def share():
    st.caption("배포한 앱 주소를 넣으면 같은 메모로 연결되는 QR이 만들어져요.")
    base = st.text_input("배포 주소", value=st.session_state.get('base_url', ''), placeholder="https://your-app.streamlit.app")
    st.caption("주소는 ? 앞부분까지만 입력하세요. localhost 주소는 다른 휴대폰에서 열리지 않아요.")
    if base:
        from urllib.parse import urlsplit, urlunsplit, urlencode
        parsed = urlsplit(base.strip())
        if parsed.scheme not in ('https', 'http') or not parsed.netloc:
            st.warning("http:// 또는 https://로 시작하는 올바른 주소를 넣어 주세요.")
            return
        st.session_state['base_url'] = base.strip()
        link = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode({'memo': book}), ''))
        image = qrcode.make(link)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        st.image(buffer.getvalue(), width=200)
        st.link_button("이 메모 열기", link, use_container_width=True)
        st.download_button("QR 이미지 저장", buffer.getvalue(), file_name="shopping-qr.png", mime="image/png", use_container_width=True)
        st.caption("이 QR/주소를 가진 사람은 메모를 보고 수정할 수 있어요. 민감한 정보는 적지 마세요.")


@st.dialog("ℹ 사용 안내")
def help_dialog():
    st.markdown("**1 꼭 필요 · 2 가격 보고 · 3 저렴할 때**\n\n➕ 상품 추가 → 담기 → 단가·수량 입력 → 총액 자동 반영.\n\n비싸면 **보류**하세요. 보류 목록에서 다시 복귀할 수 있어요. 카트 상품도 되돌릴 수 있어요.")
    st.caption("수량은 개·팩·kg 등 단가와 동일한 단위로 입력하세요. 합계는 원 단위 반올림, 별도 할인·봉투값은 실제 결제와 다를 수 있어요.")
    st.warning("저장 안내: 현재 코드는 앱 서버의 SQLite 파일에 저장합니다. Streamlit Community Cloud의 재배포·서버 재생성 시 데이터가 사라질 수 있습니다. 영구 보관이 필요하면 외부 DB를 연결해야 합니다. QR은 앱 실행 후 온라인에서 작동합니다.")
    st.caption("같은 QR로 여럿이 쓸 때 다른 사람의 변경은 하단 새로고침으로 확인하세요. 알림은 앱 안의 안내이며 휴대폰 푸시 알림은 아닙니다.")


st.markdown('''<style>
.block-container{max-width:540px;padding:0.7rem 0.8rem 1rem!important}
header[data-testid="stHeader"]{height:0!important;min-height:0!important}
h3{font-size:1.3rem!important;padding:0!important;margin:0!important}
[data-testid="stVerticalBlock"]{gap:0.45rem}
[data-testid="stHorizontalBlock"]{gap:0.4rem}
[data-testid="stMetricValue"]{font-size:1.55rem}
[data-testid="stCaptionContainer"] p{font-size:0.76rem;margin-bottom:0}
button{min-height:2.35rem!important}
[data-testid="stTextInput"] input{font-size:16px}
@media(max-width:640px){[data-testid="stHorizontalBlock"]{flex-wrap:nowrap!important}
[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:0!important;flex:1 1 0!important}}
</style>''', unsafe_allow_html=True)

st.markdown("### 🛒 장보기 알림메모")
items = rows()
cart = [r for r in items if r['status'] == 'cart']
todo = [r for r in items if r['status'] == 'todo']
hold = [r for r in items if r['status'] == 'hold']
a, b = st.columns([2, 1])
a.metric("현재 카트 총액", money(sum(r['total'] for r in cart)))
b.metric("남은 메모", f"{len(todo)}개")

buttons = st.columns(3)
if buttons[0].button("➕ 추가", use_container_width=True):
    add_item()
if buttons[1].button("📱 QR", use_container_width=True):
    share()
if buttons[2].button("ℹ 안내", use_container_width=True):
    help_dialog()

view = st.segmented_control("목록", ["살 것", "카트", "보류"], default="살 것", label_visibility="collapsed", key="view") or "살 것"
selected = {'살 것': todo, '카트': cart, '보류': hold}[view]
st.caption(f"1 꼭 필요 · 2 가격 보고 · 3 저렴할 때  |  {view} {len(selected)}개")
PAGE_SIZE = 3
pages = max(1, (len(selected) + PAGE_SIZE - 1) // PAGE_SIZE)
page_key = f"page_{view}"
st.session_state[page_key] = min(st.session_state.get(page_key, 0), pages - 1)
page = st.session_state[page_key]
if not selected:
    st.info({'살 것': '살 물건을 ➕ 추가해 주세요.', '카트': '아직 담은 상품이 없어요.', '보류': '보류한 상품이 없어요.'}[view])
for item in selected[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
    with st.container(border=True):
        # 텍스트는 Markdown이 아닌 일반 텍스트로 표시해 사용자 입력을 안전하게 처리합니다.
        st.text(f"{item['priority']} · {item['name'][:26]}{'…' if len(item['name']) > 26 else ''}")
        if view == '카트':
            st.caption(f"{money(item['price'])} × {item['quantity']:g} = {money(item['total'])}")
            if st.button("↩ 수정·되돌리기", key=f"cart_{item['id']}", use_container_width=True):
                manage_cart(item)
        else:
            st.caption(f"{item['category']} · 희망가 {money(item['ceiling']) if item['ceiling'] else '미설정'}")
            if view == '살 것':
                c, d = st.columns([2, 1])
                if c.button("🛒 담기", key=f"buy_{item['id']}", use_container_width=True):
                    purchase(item)
                if d.button("···", key=f"more_{item['id']}", use_container_width=True):
                    manage_item(item)
            elif st.button("↩ 복귀·관리", key=f"hold_{item['id']}", use_container_width=True):
                manage_item(item)

prev, indicator, nxt, refresh = st.columns(4)
if prev.button("◀", disabled=page == 0, use_container_width=True):
    st.session_state[page_key] -= 1
    st.rerun()
indicator.caption(f"{page + 1} / {pages}")
if nxt.button("▶", disabled=page >= pages - 1, use_container_width=True):
    st.session_state[page_key] += 1
    st.rerun()
if refresh.button("↻", help="공유 메모 새로고침", use_container_width=True):
    st.rerun()
if 'notice' in st.session_state:
    st.toast(st.session_state.pop('notice'))

# 배포: 이 파일과 requirements.txt를 같은 GitHub 저장소에 올리고
# Streamlit Community Cloud에서 main file path를 app.py로 지정하세요.
# 앱의 QR 버튼에 배포 URL을 입력하면 해당 메모의 QR을 내려받을 수 있습니다.
