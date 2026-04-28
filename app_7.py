# ═══════════════════════════════════════════════════
# 日语单词听力练习系统 v4.0  (Streamlit 版 + Google Drive 同步)
# 在 v3.0 基础上增加：Google Drive 云端词库自动同步
# ═══════════════════════════════════════════════════
import streamlit as st
import streamlit.components.v1 as components
import edge_tts
import asyncio
import io
import base64
import random
import datetime

# ── 页面配置（必须在所有其他 st 调用之前）──────────
st.set_page_config(
    page_title="日语听力练习",
    page_icon="🇯🇵",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── 全局 CSS ─────────────────────────────────────────
st.markdown("""
<style>
  /* 大字单词区 */
  .word-box {
      text-align: center;
      font-size: 64px;
      font-weight: 700;
      color: #2c3e50;
      letter-spacing: 4px;
      padding: 24px 0 18px;
      min-height: 110px;
      line-height: 1.1;
      font-family: 'Helvetica Neue', Arial, 'Hiragino Sans', sans-serif;
  }
  .word-box.hidden {
      color: #ecf0f1;
      text-shadow: 0 0 28px #bdc3c7;
  }
  /* 统一按钮圆角 */
  div.stButton > button { border-radius: 10px; }
  /* 音频播放器宽度 */
  audio { width: 100% !important; }
  /* 云端状态标签 */
  .cloud-badge {
      display: inline-block;
      padding: 2px 10px;
      border-radius: 20px;
      font-size: 13px;
      font-weight: 600;
  }
  .cloud-ok   { background:#d4edda; color:#155724; }
  .cloud-warn { background:#fff3cd; color:#856404; }
  .cloud-off  { background:#f8d7da; color:#721c24; }
</style>
""", unsafe_allow_html=True)

# ── 常量 ──────────────────────────────────────────────
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

# ── Google Drive 文件名（可在 secrets 里覆盖）────────
GDRIVE_FILE_NAME = "japanese_words.csv"


# ═══════════════════════════════════════════════════
# Google Drive 工具函数
# ═══════════════════════════════════════════════════

def _gdrive_enabled() -> bool:
    """判断 Streamlit secrets 里是否配置了 GCP 服务账号。"""
    try:
        return "gcp_service_account" in st.secrets
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _gdrive_service():
    """
    构建并缓存 Google Drive API 服务对象。
    需要在 .streamlit/secrets.toml 里配置：
        [gcp_service_account]
        type = "service_account"
        project_id = "..."
        private_key_id = "..."
        private_key = "-----BEGIN RSA PRIVATE KEY-----\n..."
        client_email = "..."
        ...
    """
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]),
            scopes=["https://www.googleapis.com/auth/drive"],
        )
        return build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        return None


def gdrive_find_file(service, filename: str) -> dict | None:
    """在 Drive 里搜索第一个同名文件，返回 {id, name, modifiedTime} 或 None。"""
    try:
        res = service.files().list(
            q=f"name='{filename}' and trashed=false",
            fields="files(id, name, modifiedTime)",
            orderBy="modifiedTime desc",
            pageSize=1,
        ).execute()
        files = res.get("files", [])
        return files[0] if files else None
    except Exception:
        return None


def gdrive_download_csv(service, file_id: str) -> str:
    """下载 Drive 文件内容，返回 UTF-8 字符串。"""
    from googleapiclient.http import MediaIoBaseDownload
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue().decode("utf-8-sig")


def gdrive_upload_csv(service, content: str, file_id: str | None = None,
                       filename: str = GDRIVE_FILE_NAME) -> str:
    """
    上传 CSV 到 Drive。
    - file_id 存在时：更新已有文件
    - file_id 为 None 时：新建文件，返回新 file_id
    """
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype="text/csv",
        resumable=False,
    )
    if file_id:
        service.files().update(fileId=file_id, media_body=media).execute()
        return file_id
    else:
        meta = {"name": filename}
        result = service.files().create(
            body=meta, media_body=media, fields="id"
        ).execute()
        return result.get("id")


def do_cloud_load():
    """
    从 Google Drive 加载词库 CSV 到当前 WordStore。
    在 session_state 里更新 gdrive_file_id 和 gdrive_last_sync。
    """
    if not _gdrive_enabled():
        st.error("❌ 未检测到 Google Drive 配置，请参见侧边栏说明")
        return
    service = _gdrive_service()
    if service is None:
        st.error("❌ 无法连接 Google Drive，请检查服务账号配置")
        return

    with st.spinner("☁️ 正在从 Google Drive 加载词库..."):
        finfo = gdrive_find_file(service, GDRIVE_FILE_NAME)
        if not finfo:
            st.warning(f"⚠️ Drive 里尚无 `{GDRIVE_FILE_NAME}`，请先保存一次")
            return
        csv_text = gdrive_download_csv(service, finfo["id"])

    store = st.session_state.store
    n = store.import_csv(csv_text)
    st.session_state.gdrive_file_id   = finfo["id"]
    st.session_state.gdrive_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
    if n:
        st.success(f"✅ 已从 Drive 加载 {n} 个新词  （文件：{finfo['name']}）")
    else:
        st.info("✅ Drive 词库已同步，无新词（词库已是最新）")
    st.rerun()


def do_cloud_save():
    """
    将当前词库 CSV 保存到 Google Drive（覆盖同名文件 / 新建）。
    """
    if not _gdrive_enabled():
        st.error("❌ 未检测到 Google Drive 配置，请参见侧边栏说明")
        return
    service = _gdrive_service()
    if service is None:
        st.error("❌ 无法连接 Google Drive，请检查服务账号配置")
        return

    store = st.session_state.store
    if not store.words:
        st.warning("⚠️ 词库为空，无需保存")
        return

    csv_text = store.export_csv()
    fid = st.session_state.get("gdrive_file_id")

    with st.spinner("☁️ 正在保存到 Google Drive..."):
        # 如果没有缓存的 file_id，先搜索一次
        if not fid:
            finfo = gdrive_find_file(_gdrive_service(), GDRIVE_FILE_NAME)
            fid = finfo["id"] if finfo else None
        new_fid = gdrive_upload_csv(service, csv_text, file_id=fid)

    st.session_state.gdrive_file_id   = new_fid
    st.session_state.gdrive_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
    st.success(f"✅ 已保存 {len(store.words)} 个词到 Google Drive  ✓")


# ═══════════════════════════════════════════════════
# WordStore — 与原版完全相同
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
                self.words.append({
                    'word': w, 'group': self._next_grp(gs),
                    'long_level': 0,
                    'added_date': datetime.date.today().isoformat()
                })
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
            self.words.append({
                'word': word, 'group': group,
                'long_level': level, 'added_date': date
            })
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
        return {
            'total':  len(self.words),
            'levels': lv,
            'groups': len(set(w['group'] for w in self.words))
        }


# ═══════════════════════════════════════════════════
# SessionManager — 与原版完全相同
# ═══════════════════════════════════════════════════
_INIT_STATE = {0: 3, 1: 1, 2: 2, 3: 3}
_REAPPEAR = {
    3: [('near',   4,  8), ('medium', 14, 22)],
    2: [('medium', 10, 17)],
    1: [],
}
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
        self.group_order    = sorted(gmap.keys())
        self.gmap           = gmap
        self.g_idx          = 0
        self.carryover      = {}
        self.last_carryover = []
        self.queue          = []
        self.q_pos          = 0
        self.in_loop        = False
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
        st_val = self.state[word]
        for (_, lo, hi) in _REAPPEAR.get(st_val, []):
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
        return {
            'state':   self.state.get(word, 1),
            'hist':    self.history.get(word, []),
            'dgr_cnt': sum(self.dgr.get(word, {}).values()),
        }

    def stats(self):
        done  = sum(1 for d in self.done.values() if d)
        total = len(self.done)
        return {
            'done':         done,
            'total':        total,
            'undone_count': total - done,
            'queue_rem':    max(0, len(self.queue) - self.q_pos),
            'in_loop':      self.in_loop,
            'gid':          self.current_gid(),
        }


# ═══════════════════════════════════════════════════
# TTS — 用 @st.cache_data 自动缓存，最多150条
# ═══════════════════════════════════════════════════
def _tts_in_thread(word: str, voice: str, rate: str) -> bytes:
    import threading
    result_box: list = [b""]
    error_box:  list = [None]

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
    if not t.is_alive() and not error_box[0]:
        return result_box[0]
    return b""


def render_audio(data: bytes, word: str = "", autoplay: bool = False) -> None:
    if not data:
        st.caption("⚠️ 音频未生成，请点「🔊 重播」重试")
        return

    b64      = base64.b64encode(data).decode()
    play_js  = "audio.play().catch(function(){});" if autoplay else ""
    size_kb  = len(data) // 1024

    html = f"""<!DOCTYPE html>
<html>
<head>
<style>
  body  {{ margin:0; padding:0; background:transparent; }}
  audio {{ width:100%; border-radius:8px; display:block; }}
  p     {{ font-size:11px; color:#888; margin:2px 0 0; font-family:sans-serif; }}
</style>
</head>
<body>
<!-- word={word} size={size_kb}KB -->
<audio controls id="jp-audio">
  <source src="data:audio/mpeg;base64,{b64}" type="audio/mpeg">
  <source src="data:audio/mp3;base64,{b64}"  type="audio/mp3">
</audio>
<p>📦 {size_kb} KB · {word}</p>
<script>
  var audio = document.getElementById('jp-audio');
  audio.load();
  {play_js}
</script>
</body>
</html>"""

    components.html(html, height=75, scrolling=False)


@st.cache_data(max_entries=150, show_spinner=False)
def get_audio(word: str, voice: str, rate: str) -> bytes:
    return _tts_in_thread(word, voice, rate)


# ═══════════════════════════════════════════════════
# Session State 初始化
# ═══════════════════════════════════════════════════
def _init():
    defaults = {
        'store':     WordStore(),
        'session':   None,
        'phase':     'main',
        'show_word': False,
        'voice':     'ja-JP-NanamiNeural',
        'speed':     '+0%',
        'gs':        33,
        'autoplay':  False,
        'rv_idx':    0,
        'cur_audio': b'',
        'last_audio_word': '',
        'last_file_id':     '',
        'last_file_result': None,
        # ── Google Drive 状态 ──
        'gdrive_file_id':   None,   # 缓存的 Drive 文件 ID
        'gdrive_last_sync': None,   # 上次同步时间字符串
        'gdrive_auto_load': False,  # 是否已完成启动时自动加载
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init()


# ── 启动时自动从 Drive 加载（仅执行一次）──────────────
# 只在词库为空 且 Drive 已配置时触发，避免覆盖用户本地词库
if (not st.session_state.gdrive_auto_load
        and _gdrive_enabled()
        and len(st.session_state.store.words) == 0):
    st.session_state.gdrive_auto_load = True
    service = _gdrive_service()
    if service:
        finfo = gdrive_find_file(service, GDRIVE_FILE_NAME)
        if finfo:
            try:
                csv_text = gdrive_download_csv(service, finfo["id"])
                n = st.session_state.store.import_csv(csv_text)
                st.session_state.gdrive_file_id   = finfo["id"]
                st.session_state.gdrive_last_sync = datetime.datetime.now().strftime("%H:%M:%S")
                # 用 toast 提示，不打断 UI
                st.toast(f"☁️ 已从 Google Drive 自动加载 {n} 个词", icon="✅")
            except Exception:
                pass


# ═══════════════════════════════════════════════════
# 侧边栏：Google Drive 配置说明 + 状态
# ═══════════════════════════════════════════════════
def _sidebar_gdrive():
    with st.sidebar:
        st.header("☁️ Google Drive 同步")

        enabled = _gdrive_enabled()
        last_sync = st.session_state.get("gdrive_last_sync")

        if enabled:
            badge = f'<span class="cloud-badge cloud-ok">✅ 已配置</span>'
            if last_sync:
                badge += f'<br><small>上次同步：{last_sync}</small>'
        else:
            badge = '<span class="cloud-badge cloud-off">❌ 未配置</span>'
        st.markdown(badge, unsafe_allow_html=True)

        st.divider()

        if enabled:
            c1, c2 = st.columns(2)
            with c1:
                if st.button("⬇ 从云端加载", use_container_width=True):
                    do_cloud_load()
            with c2:
                if st.button("⬆ 保存到云端", use_container_width=True):
                    do_cloud_save()
            st.caption(f"词库文件名：`{GDRIVE_FILE_NAME}`")
        else:
            st.markdown("""
**如何配置 Google Drive 同步：**

**第 1 步** — 创建服务账号
1. 打开 [Google Cloud Console](https://console.cloud.google.com/)
2. 新建项目（或使用现有项目）
3. 启用 **Google Drive API**
4. 在「IAM 与管理」→「服务账号」创建服务账号
5. 下载 JSON 密钥文件

**第 2 步** — 配置 Streamlit Secrets

在项目根目录创建 `.streamlit/secrets.toml`：

```toml
[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "key-id"
private_key = \"\"\"-----BEGIN RSA PRIVATE KEY-----
...（密钥内容）...
-----END RSA PRIVATE KEY-----\"\"\"
client_email = "xxx@yyy.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

**部署到 Streamlit Cloud 时：**
在 App Settings → Secrets 里粘贴相同内容。

**第 3 步** — 与服务账号共享 Drive 文件夹
把 `client_email` 里的邮箱加为共享者（编辑权限）即可。

配置完成后，词库将在所有设备间自动同步 ✓
""")


# ═══════════════════════════════════════════════════
# 界面：主页
# ═══════════════════════════════════════════════════
def screen_main():
    _sidebar_gdrive()

    store = st.session_state.store
    s = store.stats()

    st.title("🇯🇵 日语单词听力练习")

    # 云端状态快捷按钮（主页顶部）
    if _gdrive_enabled():
        last_sync = st.session_state.get("gdrive_last_sync")
        sync_label = f"上次同步：{last_sync}" if last_sync else "尚未同步"
        col_a, col_b, col_c = st.columns([2, 1, 1])
        col_a.caption(f"☁️ Google Drive 已连接 · {sync_label}")
        with col_b:
            if st.button("⬇ 加载", use_container_width=True, help="从 Google Drive 加载词库"):
                do_cloud_load()
        with col_c:
            if st.button("⬆ 保存", use_container_width=True, help="保存词库到 Google Drive"):
                do_cloud_save()
    else:
        st.info("💡 在左侧边栏配置 Google Drive 可实现多设备同步（iPad 等）")

    # 词库概况
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("总词数", s['total'])
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

    # 粘贴添加
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
            # 添加后自动同步到 Drive
            if _gdrive_enabled():
                do_cloud_save()
        else:
            st.warning("⚠️ 没有新词（词可能已存在）")

    st.divider()

    # CSV 上传（保留本地上传作为备用）
    st.subheader("📂 上传本地 CSV（备用）")
    st.caption("也可直接上传之前导出的 CSV，组别和长期等级将完整保留。")
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
                st.success(f"✅ 从 {fname} 导入了 {n} 个词，组别和等级已完整保留")
            else:
                st.info(f"文件 {fname} 中没有新词（可能已全部存在）")

    st.divider()

    # 词库预览 + 导出
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

        # 导出按钮
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
            if _gdrive_enabled():
                if st.button("☁️ 保存到 Drive", use_container_width=True, type="primary"):
                    do_cloud_save()
            else:
                st.caption("（配置 Drive 后启用）")


# ── 学习配置面板 ──────────────────────────────────────
def _panel_study():
    store = st.session_state.store
    if not store.words:
        st.warning("⚠️ 请先在「录入词汇」标签页添加词汇")
        return

    groups  = store.get_groups()
    all_gids = list(groups.keys())

    # 长期等级筛选
    st.caption("**筛选长期等级**")
    lc = st.columns(4)
    lv_labels   = ["0 新词", "1 掌握", "2 模糊", "3 重点"]
    lv_defaults = [True,     False,    True,     True]
    lv_sel = [i for i, (col, lbl, df) in enumerate(zip(lc, lv_labels, lv_defaults))
               if col.checkbox(lbl, value=df, key=f"lv_chk_{i}")]

    # 组别筛选
    st.caption("**筛选组别**")
    gr_sel = st.multiselect(
        "组别", all_gids, default=all_gids,
        format_func=lambda x: f"第{x}组 ({len(groups[x])}词)",
        label_visibility="collapsed",
    )

    # 语音选择
    voice_name = st.selectbox("语音", list(VOICES.keys()))

    # 预览匹配词数
    ws = store.filter(lv_sel, gr_sel)
    if ws:
        st.info(f"🎯 将练习 **{len(ws)}** 个词")
    else:
        st.warning("⚠️ 无词匹配，请调整筛选条件")

    if st.button("🎧 开始练习", type="primary",
                  disabled=(not ws), use_container_width=True):
        st.session_state.voice        = VOICES[voice_name]
        st.session_state.session      = SessionManager(ws)
        st.session_state.pop('show_word', None)
        st.session_state.last_audio_word = ''
        st.session_state.phase        = 'session'
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
    st.markdown(f'<div class="word-box{cls}">{txt}</div>',
                unsafe_allow_html=True)

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
            # 练习完成后自动同步到 Drive
            if _gdrive_enabled():
                do_cloud_save()
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
        if st.button("◀ 上一", disabled=(sess.q_pos == 0),
                     use_container_width=True):
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

    # 导出区：Drive 优先，本地下载为备用
    if _gdrive_enabled():
        col_drive, col_local = st.columns(2)
        with col_drive:
            if st.button("☁️ 保存到 Google Drive", type="primary",
                         use_container_width=True):
                do_cloud_save()
        with col_local:
            st.download_button(
                "⬇ 下载本地 CSV",
                data=st.session_state.store.export_csv(),
                file_name="japanese_words.csv",
                mime="text/csv",
                use_container_width=True,
            )
    else:
        st.download_button(
            "⬇ 导出词库 CSV（含最新长期等级）",
            data=st.session_state.store.export_csv(),
            file_name="japanese_words.csv",
            mime="text/csv",
            type="primary",
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
