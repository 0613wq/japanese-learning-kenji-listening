# ═══════════════════════════════════════════════════
# 日语单词听力练习系统 v4.1  (Streamlit + GitHub Gist 同步)
# ═══════════════════════════════════════════════════
import streamlit as st
import streamlit.components.v1 as components
import edge_tts
import asyncio
import io
import base64
import random
import datetime
import requests

st.set_page_config(
    page_title="日语听力练习",
    page_icon="🇯🇵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .word-box {
      text-align: center; font-size: 64px; font-weight: 700;
      color: #2c3e50; letter-spacing: 4px; padding: 24px 0 18px;
      min-height: 110px; line-height: 1.1;
      font-family: 'Helvetica Neue', Arial, 'Hiragino Sans', sans-serif;
  }
  .word-box.hidden { color: #ecf0f1; text-shadow: 0 0 28px #bdc3c7; }
  div.stButton > button { border-radius: 10px; }
  audio { width: 100% !important; }
</style>
""", unsafe_allow_html=True)

VOICES = {
    "🎀 七海 Nanami（女声·自然）": "ja-JP-NanamiNeural",
    "🎵 圭太 Keita（男声·自然）":  "ja-JP-KeitaNeural",
}
SPEEDS = {
    "🐢 0.75× 慢速": "-25%",
    "🐇 0.9×  稍慢": "-10%",
    "▶  1.0×  正常": "+0%",
    "⚡ 1.15× 稍快": "+15%",
    "🚀 1.3×  快速": "+30%",
}

GIST_FILENAME = "japanese_words.csv"


# ═══════════════════════════════════════════════════
# GitHub Gist 工具函数
# ═══════════════════════════════════════════════════

def _gist_cfg() -> tuple[str | None, str | None]:
    """从 secrets 读取 token 和可选的 gist_id。"""
    try:
        token   = st.secrets["github"]["token"]
        gist_id = st.secrets["github"].get("gist_id", "")
        return token, gist_id or None
    except Exception:
        return None, None


def _gist_enabled() -> bool:
    token, _ = _gist_cfg()
    return bool(token)


def _gist_headers() -> dict:
    token, _ = _gist_cfg()
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }


def gist_find(token: str) -> dict | None:
    """在用户所有 Gist 里找 GIST_FILENAME，返回 {id, updated_at} 或 None。"""
    page = 1
    while True:
        r = requests.get(
            "https://api.github.com/gists",
            headers=_gist_headers(),
            params={"per_page": 100, "page": page},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json()
        if not items:
            return None
        for item in items:
            if GIST_FILENAME in item.get("files", {}):
                return {"id": item["id"], "updated_at": item["updated_at"]}
        page += 1


def gist_load(gist_id: str) -> str:
    """下载 Gist 里 GIST_FILENAME 的内容，返回 CSV 字符串。"""
    r = requests.get(
        f"https://api.github.com/gists/{gist_id}",
        headers=_gist_headers(),
        timeout=10,
    )
    r.raise_for_status()
    raw_url = r.json()["files"][GIST_FILENAME]["raw_url"]
    content = requests.get(raw_url, timeout=10)
    content.raise_for_status()
    return content.text


def gist_save(csv_text: str, gist_id: str | None = None) -> str:
    """
    保存词库到 Gist。
    - gist_id 有值：PATCH 更新已有 Gist，返回同一 id
    - gist_id 为 None：POST 新建 Gist（公开），返回新 id
    """
    payload = {
        "description": "日语单词听力练习 — 词库自动备份",
        "files": {GIST_FILENAME: {"content": csv_text}},
    }
    if gist_id:
        r = requests.patch(
            f"https://api.github.com/gists/{gist_id}",
            headers=_gist_headers(),
            json=payload,
            timeout=10,
        )
    else:
        payload["public"] = False   # 设为 secret gist
        r = requests.post(
            "https://api.github.com/gists",
            headers=_gist_headers(),
            json=payload,
            timeout=10,
        )
    r.raise_for_status()
    return r.json()["id"]


# ── 高层操作（带 UI 反馈）────────────────────────────

def do_gist_load():
    """从 GitHub Gist 加载词库到 session_state.store。"""
    token, gist_id = _gist_cfg()
    if not token:
        st.error("❌ 未配置 GitHub Token，请查看侧边栏说明")
        return

    with st.spinner("☁️ 正在从 GitHub Gist 加载..."):
        try:
            # 优先用 secrets 里的 gist_id，否则搜索
            if not gist_id:
                info = gist_find(token)
                if not info:
                    st.warning(f"⚠️ 在你的 Gist 里没有找到 `{GIST_FILENAME}`，请先保存一次")
                    return
                gist_id = info["id"]
            csv_text = gist_load(gist_id)
        except Exception as e:
            st.error(f"❌ 加载失败：{e}")
            return

    n = st.session_state.store.import_csv(csv_text)
    st.session_state.gist_id        = gist_id
    st.session_state.gist_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
    if n:
        st.success(f"✅ 已加载 {n} 个新词")
    else:
        st.info("✅ 已同步，没有新词（词库已是最新）")
    st.rerun()


def do_gist_save():
    """将当前词库保存到 GitHub Gist。"""
    token, cfg_gist_id = _gist_cfg()
    if not token:
        st.error("❌ 未配置 GitHub Token，请查看侧边栏说明")
        return

    store = st.session_state.store
    if not store.words:
        st.warning("⚠️ 词库为空，无需保存")
        return

    # gist_id 优先级：session > secrets > 搜索
    gist_id = st.session_state.get("gist_id") or cfg_gist_id

    with st.spinner("☁️ 正在保存到 GitHub Gist..."):
        try:
            if not gist_id:
                # 先搜索一次，避免重复创建
                info = gist_find(token)
                gist_id = info["id"] if info else None
            new_id = gist_save(store.export_csv(), gist_id)
        except Exception as e:
            st.error(f"❌ 保存失败：{e}")
            return

    st.session_state.gist_id        = new_id
    st.session_state.gist_last_sync = datetime.datetime.now().strftime("%H:%M:%S")

    if not gist_id:   # 刚刚新建
        st.success(f"✅ 已新建 Secret Gist！")
        st.info(
            f"💡 **可选加速**：把下面这个 Gist ID 填入 secrets.toml 的 `gist_id`，"
            f"之后加载时就不需要搜索所有 Gist 了。\n\n`{new_id}`"
        )
    else:
        st.success(f"✅ 已保存 {len(store.words)} 个词到 GitHub Gist")


# ═══════════════════════════════════════════════════
# WordStore
# ═══════════════════════════════════════════════════
class WordStore:
    def __init__(self):
        self.words = []

    def _exists(self):
        return {w['word'] for w in self.words}

    def _next_grp(self, gs):
        return (len(self.words) // gs) + 1

    def add_text(self, text, gs=33):
        ex = self._exists()
        added = 0
        for line in text.splitlines():
            w = line.strip()
            if w and w not in ex:
                self.words.append({'word': w, 'group': self._next_grp(gs),
                                   'long_level': 0,
                                   'added_date': datetime.date.today().isoformat()})
                ex.add(w)
                added += 1
        return added

    def import_csv(self, text, gs=33):
        ex = self._exists()
        added = 0
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith('word'):
                continue
            parts = line.split(',')
            word = parts[0].strip()
            if not word or word in ex:
                continue
            try:
                group = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip() else self._next_grp(gs)
            except Exception:
                group = self._next_grp(gs)
            try:
                level = max(0, min(3, int(parts[2].strip()))) if len(parts) > 2 else 0
            except Exception:
                level = 0
            date = parts[3].strip() if len(parts) > 3 else datetime.date.today().isoformat()
            self.words.append({'word': word, 'group': group,
                               'long_level': level, 'added_date': date})
            ex.add(word)
            added += 1
        return added

    def update_long(self, word, level):
        for w in self.words:
            if w['word'] == word:
                w['long_level'] = level
                return

    def get_groups(self):
        gs = {}
        for w in self.words:
            gs.setdefault(w['group'], []).append(w)
        return dict(sorted(gs.items()))

    def filter(self, levels, groups):
        return [w for w in self.words
                if w['long_level'] in levels and w['group'] in groups]

    def export_csv(self):
        lines = ['word,group,long_level,added_date']
        for w in self.words:
            lines.append(f"{w['word']},{w['group']},{w['long_level']},{w['added_date']}")
        return '\n'.join(lines)

    def stats(self):
        lv = [0, 0, 0, 0]
        for w in self.words:
            lv[w['long_level']] += 1
        return {'total': len(self.words), 'levels': lv,
                'groups': len(set(w['group'] for w in self.words))}


# ═══════════════════════════════════════════════════
# SessionManager
# ═══════════════════════════════════════════════════
_INIT_STATE    = {0: 3, 1: 1, 2: 2, 3: 3}
_REAPPEAR      = {3: [('near', 4, 8), ('medium', 14, 22)], 2: [('medium', 10, 17)], 1: []}
_CARRYOVER_SLOTS = {3: 2, 2: 1}

class SessionManager:
    def __init__(self, words):
        self.word_map  = {w['word']: w for w in words}
        self.state     = {w['word']: _INIT_STATE[w['long_level']] for w in words}
        self.done      = {w['word']: (w['long_level'] == 1) for w in words}
        self.dgr       = {w['word']: {} for w in words}
        self.history   = {w['word']: [] for w in words}
        gmap = {}
        for w in words:
            gmap.setdefault(w['group'], []).append(w['word'])
        self.group_order = sorted(gmap.keys())
        self.gmap        = gmap
        self.g_idx       = 0
        self.carryover   = {}
        self.last_carryover = []
        self.queue       = []
        self.q_pos       = 0
        self.in_loop     = False
        self._build_queue()

    def _build_queue(self):
        gid  = self.group_order[self.g_idx]
        main = [w for w in self.gmap[gid] if not self.done[w]]
        random.shuffle(main)
        combined = list(main)
        for w, slots in self.carryover.items():
            for _ in range(slots):
                combined.insert(random.randint(0, len(combined)), w)
        self.carryover = {}
        self.queue = combined
        self.q_pos = 0

    def current_word(self):
        return self.queue[self.q_pos] if self.q_pos < len(self.queue) else None

    def _reinsert(self, word):
        for (_, lo, hi) in _REAPPEAR.get(self.state[word], []):
            dist = max(3, random.randint(lo, hi))
            pos  = min(self.q_pos + dist, len(self.queue))
            self.queue.insert(pos, word)

    def rate(self, word, button):
        self.history[word].append(button)
        curr = self.state[word]
        if button < curr:
            self.state[word] = button
            self.dgr[word]   = {}
        elif button > curr:
            self.dgr[word][button] = self.dgr[word].get(button, 0) + 1
            if self.dgr[word][button] >= 3:
                self.state[word] = min(3, curr + 1)
                self.dgr[word]   = {}
        else:
            self.dgr[word] = {}
        if self.state[word] == 1:
            self.done[word] = True
        else:
            self.done[word] = False
            self._reinsert(word)
        self.q_pos += 1
        if self.is_done():
            return 'session_done'
        if self.q_pos >= len(self.queue):
            return self._advance()
        return 'continue'

    def _advance(self):
        if self.in_loop:
            undone = [w for w, d in self.done.items() if not d]
            if undone:
                random.shuffle(undone)
                self.queue = undone
                self.q_pos = 0
                return 'continue'
            return 'session_done'
        gid = self.group_order[self.g_idx]
        new_carry = {}
        self.last_carryover = []
        for w in self.gmap[gid]:
            st_val = self.state[w]
            if not self.done[w] and st_val in _CARRYOVER_SLOTS:
                new_carry[w] = _CARRYOVER_SLOTS[st_val]
                self.last_carryover.append(w)
        self.g_idx += 1
        if self.g_idx < len(self.group_order):
            self.carryover = new_carry
            self._build_queue()
            return 'group_done'
        else:
            undone = [w for w, d in self.done.items() if not d]
            if undone:
                self.in_loop = True
                self.last_carryover = list(undone)
                random.shuffle(undone)
                self.queue = undone
                self.q_pos = 0
                return 'group_done'
            return 'session_done'

    def is_done(self):
        return all(self.done.values())

    def prev(self):
        if self.q_pos > 0:
            self.q_pos -= 1
            return True
        return False

    def skip(self):
        word = self.current_word()
        if word:
            self._reinsert(word)
        self.q_pos += 1
        if self.is_done():
            return 'session_done'
        if self.q_pos >= len(self.queue):
            return self._advance()
        return 'continue'

    def current_gid(self):
        if self.in_loop or self.g_idx >= len(self.group_order):
            return None
        return self.group_order[self.g_idx]

    def word_detail(self, word):
        return {'state':   self.state.get(word, 1),
                'hist':    self.history.get(word, []),
                'dgr_cnt': sum(self.dgr.get(word, {}).values())}

    def stats(self):
        done  = sum(1 for d in self.done.values() if d)
        total = len(self.done)
        return {'done': done, 'total': total,
                'undone_count': total - done,
                'queue_rem':    max(0, len(self.queue) - self.q_pos),
                'in_loop':      self.in_loop,
                'gid':          self.current_gid()}


# ═══════════════════════════════════════════════════
# TTS
# ═══════════════════════════════════════════════════
def _tts_in_thread(word, voice, rate):
    import threading
    result_box = [b""]
    error_box  = [None]

    async def _stream():
        com = edge_tts.Communicate(word, voice, rate=rate)
        buf = io.BytesIO()
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result_box[0] = loop.run_until_complete(_stream())
        except Exception as e:
            error_box[0] = e
        finally:
            loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=15)
    return result_box[0] if (not t.is_alive() and not error_box[0]) else b""


def render_audio(data, word="", autoplay=False):
    if not data:
        st.caption("⚠️ 音频未生成，请点「🔊 重播」重试")
        return
    b64     = base64.b64encode(data).decode()
    play_js = "audio.play().catch(function(){});" if autoplay else ""
    size_kb = len(data) // 1024
    html = f"""<!DOCTYPE html><html><head>
<style>body{{margin:0;padding:0;background:transparent;}}audio{{width:100%;border-radius:8px;display:block;}}p{{font-size:11px;color:#888;margin:2px 0 0;font-family:sans-serif;}}</style>
</head><body>
<audio controls id="jp-audio"><source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg"></audio>
<p>📦 {size_kb} KB · {word}</p>
<script>var audio=document.getElementById('jp-audio');audio.load();{play_js}</script>
</body></html>"""
    components.html(html, height=75, scrolling=False)


@st.cache_data(max_entries=150, show_spinner=False)
def get_audio(word, voice, rate):
    return _tts_in_thread(word, voice, rate)


# ═══════════════════════════════════════════════════
# Session State 初始化
# ═══════════════════════════════════════════════════
def _init():
    defaults = {
        'store':            WordStore(),
        'session':          None,
        'phase':            'main',
        'show_word':        False,
        'voice':            'ja-JP-NanamiNeural',
        'speed':            '+0%',
        'gs':               33,
        'autoplay':         False,
        'rv_idx':           0,
        'cur_audio':        b'',
        'last_audio_word':  '',
        'last_file_id':     '',
        'last_file_result': None,
        # Gist 状态
        'gist_id':          None,
        'gist_last_sync':   None,
        'gist_auto_loaded': False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()

# ── 启动时自动加载（词库为空时静默执行一次）──────────
if (not st.session_state.gist_auto_loaded
        and _gist_enabled()
        and len(st.session_state.store.words) == 0):
    st.session_state.gist_auto_loaded = True
    try:
        token, gist_id = _gist_cfg()
        if not gist_id:
            info = gist_find(token)
            gist_id = info["id"] if info else None
        if gist_id:
            csv_text = gist_load(gist_id)
            n = st.session_state.store.import_csv(csv_text)
            st.session_state.gist_id        = gist_id
            st.session_state.gist_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
            st.toast(f"☁️ 已从 GitHub Gist 自动加载 {n} 个词", icon="✅")
    except Exception:
        pass   # 静默失败，不打断 UI


# ═══════════════════════════════════════════════════
# 侧边栏：Gist 状态 + 配置说明
# ═══════════════════════════════════════════════════
def _sidebar_gist():
    with st.sidebar:
        st.header("🐙 GitHub Gist 同步")
        enabled   = _gist_enabled()
        last_sync = st.session_state.gist_last_sync

        if enabled:
            st.success(f"已连接{'  ·  上次同步：' + last_sync if last_sync else ''}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("⬇ 加载", use_container_width=True):
                    do_gist_load()
            with c2:
                if st.button("⬆ 保存", use_container_width=True):
                    do_gist_save()
            gid = st.session_state.gist_id
            if gid:
                st.caption(f"Gist ID: `{gid[:12]}…`")
        else:
            st.warning("未配置")
            st.markdown("""
**配置步骤（5 分钟）：**

**1. 生成 GitHub Token**
→ GitHub → Settings → Developer settings
→ Personal access tokens → Tokens (classic)
→ Generate new token
→ 勾选 **`gist`** 权限 → 生成并复制

**2. 新建配置文件**

项目目录里创建 `.streamlit/secrets.toml`：

```toml
[github]
token = "ghp_你的token"
```

**3. 部署到 Streamlit Cloud 时**

App Settings → Secrets → 粘贴相同内容

---
首次保存后 App 会显示 Gist ID，
可选填到 secrets 里加速后续加载：

```toml
[github]
token = "ghp_你的token"
gist_id = "abc123..."   # 可选
```
""")


# ═══════════════════════════════════════════════════
# 界面：主页
# ═══════════════════════════════════════════════════
def screen_main():
    _sidebar_gist()

    store = st.session_state.store
    s     = store.stats()

    st.title("🇯🇵 日语单词听力练习")

    # 顶部云端快捷栏
    if _gist_enabled():
        last_sync = st.session_state.gist_last_sync
        sync_txt  = f"上次同步：{last_sync}" if last_sync else "尚未同步"
        ca, cb, cc = st.columns([2, 1, 1])
        ca.caption(f"🐙 GitHub Gist 已连接  ·  {sync_txt}")
        with cb:
            if st.button("⬇ 加载", use_container_width=True, help="从 Gist 加载词库"):
                do_gist_load()
        with cc:
            if st.button("⬆ 保存", use_container_width=True, help="保存词库到 Gist"):
                do_gist_save()
    else:
        st.info("💡 在左侧边栏配置 GitHub Token 可实现多设备词库同步")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总词数",   s['total'])
    c2.metric("0级 新词", s['levels'][0])
    c3.metric("1级 掌握", s['levels'][1])
    c4.metric("2级 模糊", s['levels'][2])
    c5.metric("3级 重点", s['levels'][3])

    tab_in, tab_st = st.tabs(["📝 录入词汇", "🎧 开始学习"])
    with tab_in:
        _panel_input()
    with tab_st:
        _panel_study()


# ── 录入面板 ─────────────────────────────────────────
def _panel_input():
    store = st.session_state.store

    st.subheader("粘贴添加")
    raw  = st.text_area("每行一个日语词", height=130, label_visibility="collapsed",
                         placeholder="食べる\n飲む\nきれい\n勉強する")
    gs_v = st.number_input("每组词数", min_value=5, max_value=200,
                            value=st.session_state.gs, step=1)

    if st.button("➕ 添加词汇", type="primary"):
        n = store.add_text(raw, int(gs_v))
        st.session_state.gs = int(gs_v)
        if n:
            st.success(f"✅ 添加了 {n} 个新词")
            if _gist_enabled():
                do_gist_save()
        else:
            st.warning("⚠️ 没有新词（词可能已存在）")

    st.divider()

    st.subheader("📂 上传本地 CSV（备用）")
    st.caption("也可上传之前导出的 CSV，组别和长期等级将完整保留。")
    uploaded = st.file_uploader("选择 CSV 文件", type=["csv"],
                                 label_visibility="collapsed")
    if uploaded is not None:
        file_id = f"{uploaded.name}_{uploaded.size}"
        if st.session_state.last_file_id != file_id:
            try:
                text = uploaded.read().decode("utf-8-sig")
                n    = store.import_csv(text, int(gs_v))
                st.session_state.last_file_id     = file_id
                st.session_state.last_file_result = (uploaded.name, n)
            except Exception as e:
                st.error(f"读取失败：{e}")
        if st.session_state.last_file_result:
            fname, n = st.session_state.last_file_result
            if n:
                st.success(f"✅ 从 {fname} 导入了 {n} 个词")
            else:
                st.info(f"文件 {fname} 中没有新词（可能已全部存在）")

    st.divider()

    st.subheader("当前词库")
    groups = store.get_groups()
    if not groups:
        st.caption("（词库为空，请先添加词汇）")
    else:
        lv_icon = {0: "⬜", 1: "🟩", 2: "🟨", 3: "🟥"}
        for gid, words in groups.items():
            with st.expander(f"第 {gid} 组 — {len(words)} 词"):
                st.write("　".join(
                    f"{lv_icon[w['long_level']]} {w['word']}" for w in words))

        col_dl, col_up = st.columns(2)
        with col_dl:
            st.download_button(
                "⬇ 下载本地 CSV",
                data=store.export_csv(),
                file_name="japanese_words.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_up:
            if _gist_enabled():
                if st.button("🐙 保存到 Gist", use_container_width=True, type="primary"):
                    do_gist_save()


# ── 学习配置面板 ──────────────────────────────────────
def _panel_study():
    store = st.session_state.store
    if not store.words:
        st.warning("⚠️ 请先在「录入词汇」标签页添加词汇")
        return

    groups   = store.get_groups()
    all_gids = list(groups.keys())

    st.caption("**筛选长期等级**")
    lc = st.columns(4)
    lv_labels   = ["0 新词", "1 掌握", "2 模糊", "3 重点"]
    lv_defaults = [True,     False,    True,     True]
    lv_sel = [i for i, (col, lbl, df) in enumerate(zip(lc, lv_labels, lv_defaults))
               if col.checkbox(lbl, value=df, key=f"lv_chk_{i}")]

    st.caption("**筛选组别**")
    gr_sel = st.multiselect(
        "组别", all_gids, default=all_gids,
        format_func=lambda x: f"第{x}组 ({len(groups[x])}词)",
        label_visibility="collapsed",
    )

    voice_name = st.selectbox("语音", list(VOICES.keys()))
    ws = store.filter(lv_sel, gr_sel)
    if ws:
        st.info(f"🎯 将练习 **{len(ws)}** 个词")
    else:
        st.warning("⚠️ 无词匹配，请调整筛选条件")

    if st.button("🎧 开始练习", type="primary",
                  disabled=(not ws), use_container_width=True):
        st.session_state.voice           = VOICES[voice_name]
        st.session_state.session         = SessionManager(ws)
        st.session_state.pop('show_word', None)
        st.session_state.last_audio_word = ''
        st.session_state.phase           = 'session'
        st.rerun()


# ═══════════════════════════════════════════════════
# 界面：练习
# ═══════════════════════════════════════════════════
def screen_session():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = 'main'
        st.rerun()

    s    = sess.stats()
    word = sess.current_word()
    if not word:
        return

    if word != st.session_state.last_audio_word:
        with st.spinner("🎵 加载音频..."):
            st.session_state.cur_audio = get_audio(
                word, st.session_state.voice, st.session_state.speed)
        st.session_state.last_audio_word = word
        st.session_state.autoplay = True

    det  = sess.word_detail(word)
    _sl  = {1: "✅ 认识", 2: "🟡 模糊", 3: "❌ 不会"}
    gstr = f"第 {s['gid']} 组" if s['gid'] else "🔁 收尾循环"

    dgr_tip = f" · 降级进度 {det['dgr_cnt']}/3" if det['dgr_cnt'] else ""
    st.caption(
        f"**{gstr}** · 队列剩余 {s['queue_rem']} · "
        f"已通过 {s['done']}/{s['total']} · "
        f"{_sl[det['state']]}{dgr_tip}"
    )
    st.progress(s['done'] / max(s['total'], 1))

    show_now = st.session_state.get('show_word', False)
    cls = "" if show_now else " hidden"
    txt = word if show_now else "？"
    st.markdown(f'<div class="word-box{cls}">{txt}</div>', unsafe_allow_html=True)
    st.toggle("👁 显示单词", key='show_word')

    autoplay = st.session_state.autoplay
    st.session_state.autoplay = False
    if st.session_state.cur_audio:
        st.audio(st.session_state.cur_audio, format='audio/mpeg', autoplay=autoplay)
    else:
        st.caption("⚠️ 音频未生成，请点「🔊 重播」")

    col_sp, col_rp = st.columns([3, 1])
    with col_sp:
        spd_name = st.selectbox(
            "速度", list(SPEEDS.keys()),
            index=list(SPEEDS.values()).index(st.session_state.speed),
            label_visibility="collapsed",
        )
        st.session_state.speed = SPEEDS[spd_name]
    with col_rp:
        if st.button("🔊 重播", use_container_width=True):
            st.session_state.last_audio_word = ''
            st.rerun()

    st.divider()
    st.caption("**短期评级** — 立即影响播放队列")

    def do_rate(lv):
        st.session_state.pop('show_word', None)
        result = sess.rate(word, lv)
        if result == 'session_done':
            st.session_state.phase = 'done'
            if _gist_enabled():
                do_gist_save()     # 练习完成自动保存
        elif result == 'group_done':
            st.session_state.phase = 'group_done'
        st.rerun()

    bc1, bc2, bc3 = st.columns(3)
    with bc1:
        if st.button("① 认识", use_container_width=True, type="secondary"):
            do_rate(1)
    with bc2:
        if st.button("② 模糊", use_container_width=True):
            do_rate(2)
    with bc3:
        if st.button("③ 不会", use_container_width=True, type="primary"):
            do_rate(3)

    nc1, nc2, nc3 = st.columns(3)
    with nc1:
        if st.button("◀ 上一", disabled=(sess.q_pos == 0), use_container_width=True):
            if sess.prev():
                st.session_state.pop('show_word', None)
                st.rerun()
    with nc2:
        if st.button("跳过 ▶", use_container_width=True):
            result = sess.skip()
            st.session_state.pop('show_word', None)
            if result == 'session_done':
                st.session_state.phase = 'done'
            elif result == 'group_done':
                st.session_state.phase = 'group_done'
            st.rerun()
    with nc3:
        if st.button("⏹ 退出", use_container_width=True):
            st.session_state.phase   = 'main'
            st.session_state.session = None
            st.rerun()

    cur_lv = sess.word_map[word]['long_level']
    with st.expander(f"长期评级（当前 {cur_lv} 级）"):
        lv_map = {0: "0 新词", 1: "1 掌握", 2: "2 模糊", 3: "3 重点"}
        lc1, lc2, lc3, lc4 = st.columns(4)
        for lv, col in zip([0, 1, 2, 3], [lc1, lc2, lc3, lc4]):
            btn_type = "primary" if lv == cur_lv else "secondary"
            if col.button(lv_map[lv], key=f"long_{lv}",
                          use_container_width=True, type=btn_type):
                st.session_state.store.update_long(word, lv)
                st.toast(f"✅ 已保存为长期 {lv} 级")
                st.rerun()


# ═══════════════════════════════════════════════════
# 界面：组间过渡
# ═══════════════════════════════════════════════════
def screen_group_done():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = 'main'
        st.rerun()

    s     = sess.stats()
    carry = sess.last_carryover

    if s['in_loop']:
        st.info(f"🔁 **进入收尾循环** — {len(carry)} 个词将继续出现，直到全部通过")
    else:
        gid = s['gid'] or '（最后）'
        st.info(f"📋 **进入第 {gid} 组** — {len(carry)} 个上组词将随机混入新组")

    st.markdown(f"已通过：**{s['done']}** / {s['total']}")
    if carry:
        st.markdown("**携带词（未完成）：**")
        st.write("　".join(carry))
    else:
        st.success("✅ 上一组词全部通过！")

    if st.button("继续 ▶", type="primary", use_container_width=True):
        st.session_state.phase = 'session'
        st.rerun()
    if st.button("⏹ 退出练习", use_container_width=True):
        st.session_state.phase   = 'main'
        st.session_state.session = None
        st.rerun()


# ═══════════════════════════════════════════════════
# 界面：完成
# ═══════════════════════════════════════════════════
def screen_done():
    sess = st.session_state.session
    if not sess:
        st.session_state.phase = 'main'
        st.rerun()

    s = sess.stats()
    st.balloons()
    st.success(f"🎉 练习完成！共 {s['total']} 个词全部短期通过 ✓")

    all_words = sorted(sess.word_map.values(), key=lambda w: -w['long_level'])
    rv_words  = [w['word'] for w in all_words]

    if rv_words:
        st.subheader("按长期等级顺序复习")
        idx  = max(0, min(st.session_state.rv_idx, len(rv_words) - 1))
        rw   = rv_words[idx]
        rlv  = sess.word_map[rw]['long_level']
        rlbl = {0: "新词", 1: "已掌握", 2: "模糊", 3: "重点"}[rlv]
        st.markdown(f'<div class="word-box">{rw}</div>', unsafe_allow_html=True)
        st.caption(f"长期 {rlv} 级（{rlbl}）— {idx+1} / {len(rv_words)}")
        if st.button("🔊 播放发音", use_container_width=True):
            audio = get_audio(rw, st.session_state.voice, st.session_state.speed)
            render_audio(audio, word=rw, autoplay=True)
        rc1, rc2 = st.columns(2)
        if rc1.button("◀ 上一个", use_container_width=True):
            if idx > 0:
                st.session_state.rv_idx = idx - 1
                st.rerun()
        if rc2.button("下一个 ▶", use_container_width=True):
            if idx < len(rv_words) - 1:
                st.session_state.rv_idx = idx + 1
                st.rerun()

    st.divider()
    st.subheader("词汇总览")
    lv_names = {0: "新词", 1: "已掌握", 2: "模糊", 3: "重点"}
    for lv in [3, 2, 1, 0]:
        ws = [w['word'] for w in all_words if w['long_level'] == lv]
        if ws:
            st.markdown(f"**{lv}级 {lv_names[lv]}（{len(ws)}个）**")
            st.write("　".join(ws))

    st.divider()

    col_gist, col_dl = st.columns(2)
    with col_gist:
        if _gist_enabled():
            if st.button("🐙 保存到 GitHub Gist", type="primary",
                         use_container_width=True):
                do_gist_save()
        else:
            st.caption("配置 GitHub Token 后可直接同步到云端")
    with col_dl:
        st.download_button(
            "⬇ 下载本地 CSV",
            data=st.session_state.store.export_csv(),
            file_name="japanese_words.csv",
            mime="text/csv",
            use_container_width=True,
        )

    if st.button("🏠 返回主页", use_container_width=True):
        st.session_state.phase   = 'main'
        st.session_state.session = None
        st.session_state.rv_idx  = 0
        st.rerun()


# ═══════════════════════════════════════════════════
# 路由
# ═══════════════════════════════════════════════════
{
    'main':       screen_main,
    'session':    screen_session,
    'group_done': screen_group_done,
    'done':       screen_done,
}.get(st.session_state.phase, screen_main)()
