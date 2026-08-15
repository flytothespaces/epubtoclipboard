import os
import sys
import json
import zipfile
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup

from kivy.app import App
from kivy.config import Config
Config.set('graphics', 'width', '500')
Config.set('graphics', 'height', '750')
from kivy.core.window import Window
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup
from kivy.core.text import LabelBase
from kivy.lang import Builder
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.spinner import Spinner
from kivy.clock import Clock
from kivy.uix.slider import Slider

# from kivy.uix.widget import Widget

# ──────────────────────────────────────────────
# 🎯 BASE_DIR: 4개 환경을 단 한 번에 처리
# ──────────────────────────────────────────────
_IS_ANDROID = (platform == 'android') or ('ANDROID_ARGUMENT' in os.environ)
_IS_FROZEN  = getattr(sys, 'frozen', False)   # PyInstaller EXE 여부

if _IS_FROZEN:
    # ① Windows EXE: sys.executable = 실제 EXE 파일 경로
    BASE_DIR = os.path.dirname(sys.executable)
elif _IS_ANDROID:
    # ② Buildozer APK / Pydroid3:
    #    __file__ 은 읽기전용 패키지 내부이므로 사용 금지
    #    → 공용 내문서를 직접 BASE_DIR 로 지정
    BASE_DIR = "/storage/emulated/0/Documents"
else:
    # ③ PC .py 실행 (개발 환경)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 작업 디렉토리도 임시폴더가 아닌 BASE_DIR 로 고정
if not _IS_ANDROID:
    os.chdir(BASE_DIR)

# ──────────────────────────────────────────────
# 🎯 폰트 경로 설정
# ──────────────────────────────────────────────
if _IS_FROZEN and hasattr(sys, '_MEIPASS'):
    # EXE 번들 내부 임시 압축해제 폴더 (폰트는 여기서 읽어야 함)
    font_path = os.path.join(sys._MEIPASS, "cjkfont.otf")
elif _IS_ANDROID:
    # Buildozer: assets 에 포함된 파일은 앱 내부 경로로 접근
    font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cjkfont.otf")
else:
    # PC .py 실행
    font_path = os.path.join(BASE_DIR, "cjkfont.otf")

if os.path.exists(font_path):
    LabelBase.register(name="Roboto", fn_regular=font_path, fn_bold=font_path)
    print(f"[INFO] 폰트 등록 성공: {font_path}")
else:
    print(f"[WARNING] cjkfont.otf 없음 ({font_path}) — 한글 깨질 수 있음")

# 전역 마스터 KV 룰 패치 (차분한 화이트+그레이 톤 매칭)
Builder.load_string("""
<Label>:
    font_name: "Roboto"
    color: 0.15, 0.15, 0.15, 1  # 눈이 편안한 짙은 그레이/차콜 글자색
<Button>:
    font_name: "Roboto"
    background_normal: ''
    background_color: 0.35, 0.35, 0.35, 1  # 튀지 않는 차분한 미디움 그레이
    color: 1, 1, 1, 1
<TextInput>:
    font_name: "Roboto"
""")
# ----------------------------------------------------

# 키보드가 올라올 때, 활성화된 입력창(TextInput)의 위치에 맞춰
# 앱 화면 전체를 위로 슥 밀어 올려주는 모드 락인!
Window.softinput_mode = "below_target"

try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None

try:
    import androidhelper

    droid = androidhelper.Android()
except ImportError:
    droid = None


class PureEpubParser:
    def __init__(self, epub_path):
        self.path = epub_path
        self.zip_file = zipfile.ZipFile(epub_path)
        self.opf_dir = ""
        self.spine_items = []
        self._parse_manifest()

    def _parse_manifest(self):
        container_xml = self.zip_file.read("META-INF/container.xml")
        root = ET.fromstring(container_xml)
        ns = {'ns': 'urn:oasis:names:tc:opendocument:xmlns:container'}
        opf_path = root.find('.//ns:rootfile', ns).attrib['full-path']

        if "/" in opf_path:
            self.opf_dir = opf_path.rsplit("/", 1)[0] + "/"
        else:
            self.opf_dir = ""

        opf_xml = self.zip_file.read(opf_path)
        opf_root = ET.fromstring(opf_xml)

        ns_match = re.match(r'\{.*}', opf_root.tag)
        ns_url = ns_match.group(0)[1:-1] if ns_match else "http://www.idpf.org/2007/opf"
        opf_ns = {'opf': ns_url}

        manifest = {}
        for item in opf_root.findall('.//opf:manifest/opf:item', opf_ns):
            item_id = item.attrib.get('id')
            href = item.attrib.get('href')
            manifest[item_id] = self.opf_dir + href

        for itemref in opf_root.findall('.//opf:spine/opf:itemref', opf_ns):
            idref = itemref.attrib.get('idref')
            if idref in manifest:
                full_href = manifest[idref]
                if full_href.endswith(('.html', '.xhtml', '.htm')):
                    self.spine_items.append(full_href)

    def get_chapters(self):
        chapters = []
        for index, href in enumerate(self.spine_items):
            try:
                html_data = self.zip_file.read(href).decode('utf-8', errors='ignore')
                soup = BeautifulSoup(html_data, "html.parser")

                title = ""
                for h in ['h1', 'h2', 'h3', 'h4']:
                    h_tag = soup.find(h)
                    if h_tag and h_tag.get_text().strip():
                        title = h_tag.get_text().strip()
                        break

                if not title:
                    title_tag = soup.find('title')
                    if title_tag and title_tag.get_text().strip():
                        title = title_tag.get_text().strip()

                if not title:
                    title = Path(href).stem
                    if any(x in title.lower() for x in ['item', 'chapter', 'section']):
                        title = f"본문 파트 {index + 1}"

                chapters.append({
                    "title": title,
                    "href": href
                })
            except Exception as e:
                print(f"파일 추출 실패 ({href}):", e)
        return chapters

# ──────────────────────────────────────────────
# 🎯 공통 헬퍼: epubtoclipb_db 폴더 경로를 한 곳에서 결정
# ──────────────────────────────────────────────
def _get_db_dir(user_data_dir=None):
    """
    플랫폼에 관계없이 epubtoclipb_db 폴더의 절대경로를 반환.
    생성 실패 시 None 반환.

    우선순위:
      Android  → 공용 내문서 → user_data_dir(앱 내부)
      PC / EXE → BASE_DIR 옆 epubtoclipb_db (임시폴더 절대 불가)
    """
    if _IS_ANDROID:
        candidates = [
            "/storage/emulated/0/Documents/epubtoclipb_db",
        ]
        if user_data_dir:
            candidates.append(os.path.join(user_data_dir, "epubtoclipb_db"))
    else:
        # _IS_FROZEN 이든 일반 .py 든 BASE_DIR 은 이미 올바르게 설정됨
        candidates = [
            os.path.join(BASE_DIR, "epubtoclipb_db"),
        ]

    for path in candidates:
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except Exception as e:
            print(f"[경로 생성 실패] {path} : {e}")

    return None



class EpubViewerApp(App):
    def __init__(self, **kwargs):
        # 💡 Buildozer 컴파일 및 Kivy 핵심 엔진 구동을 위해 부모 초기화 필수!
        super(EpubViewerApp, self).__init__(**kwargs)

        # ◼️ [상태 및 데이터 관리 변수]
        self.translated_titles = {}
        self.is_translated = False
        self.chapters = []
        self.current_filename = ""
        self.current_index = -1
        self.epub_path = ""  # load_epub, get_chapter_text에서 사용됨
        # self.progress_file = "progress.json"

        # ◼️ [하위 메서드에서 참조하는 UI 위젯 변수 명시적 선언]
        # 인스턴스 생성 시점에 미리 구조를 잡아두어 dynamic attribute 경고를 방지합니다.
        self.file_label = None
        self.info_label = None
        self.trans_btn = None
        self.list_container = None
        self.current_title = None
        self.chapter_entry = None
        self.bundle_entry = None
        self.next_btn = None
        self.progress_label = None
        self.memo_text = ""  # 💡 메모장 텍스트 저장용 변수 추가
        try:
            memo_path = self.get_memo_file_path()
            if os.path.exists(memo_path):
                with open(memo_path, "r", encoding="utf-8") as f:
                    self.memo_text = f.read()
        except Exception as e:
            print("메모 로드 실패:", e)

        # =========================================================
        # 텍스트 탭 전역 폰트 크기
        #
        # progress.json의 _global.text_font_size에서 불러온다.
        # 값이 없으면 기본값 14를 사용한다.
        # =========================================================
        self.text_font_size = 14
        
        # 붙여넣기/번역 텍스트 관련
        self.trans_text_input = None
        self.trans_file_path = None

        # 텍스트 읽기 진행 위치
        self.trans_read_position = 0

        # =========================================================
        # 텍스트 탭 스크롤 저장값
        #
        # progress.json에 정상적인 trans 정보가 이미 존재하면
        # 기존 scroll_y를 유지한다.
        # =========================================================
        self.saved_scroll_y = 0.0

        # =========================================================
        # trans 초기화 상태
        #
        # True:
        #   progress.json에 정상적인 trans.filename + 실제 파일
        #   + scroll_y가 모두 존재함
        #
        # False:
        #   위 조건 중 하나라도 만족하지 않음.
        #
        # False 상태에서는 "붙여넣기"를 처음 실행할 때만
        # trans.filename / scroll_y=0 을 생성한다.
        # =========================================================
        self.trans_initialized = False

        # 프로그램이 의도적으로 TextInput.scroll_y를 변경하는 동안
        # on_scroll_y가 저장을 발생시키지 않도록 하는 보호 플래그
        self._suppress_scroll_save = False

        # 현재 동작이 사용자의 실제 스크롤인지 표시
        self._user_scroll_action = False

        # 텍스트 진행도 저장 예약 이벤트
        self._trans_progress_save_event = None



    # 💡 [핵심] 앱이 백그라운드로 내려갈 때 호출됨
    def on_pause(self):
        # True를 반환하면 OS에게 "나 죽이지 말고 메모리에 일시정지 상태로 살려둬"라고 요청합니다.
        print("앱이 백그라운드로 전환됨 (일시정지)")
        return True

    # 💡 앱이 다시 포그라운드로 복귀할 때 호출됨
    def on_resume(self):
        # 다시 돌아왔을 때 특별히 화면을 갱신하거나 할 필요가 없다면 pass 합니다.
        print("앱으로 다시 돌아옴 (복귀)")
        pass

    def build(self):
        # 모바일 배경색 흰색 계열 락인
        Window.clearcolor = (0.95, 0.95, 0.95, 1)

        # 💡 1. 안드로이드 백키 / PC Esc 키 감지
        Window.bind(on_keyboard=self.on_hardware_back)

        # 💡 2. 윈도우 우상단 X 버튼 클릭 감지
        Window.bind(on_request_close=self.on_window_close)

        # [마스터 레이아웃] 화면 전체를 컨테이너로 지정
        main_layout = BoxLayout(orientation="vertical", padding=10, spacing=5)

        # =========================================================================
        # ◼️ [상단 프레임 - 20%] 파일 선택 및 진행도 영역
        # =========================================================================
        top_frame = BoxLayout(orientation="vertical", size_hint_y=0.1, spacing=5)

        # [상단 1행 - 40%] 파일 선택
        file_row = BoxLayout(orientation="horizontal", size_hint_y=0.4, spacing=10)
        self.file_label = Label(text="EPUB 파일을 선택하세요", halign="left", valign="middle")
        self.file_label.bind(size=lambda obj, val: setattr(obj, 'text_size', (val[0], None)))
        file_btn = Button(text="파일 선택", size_hint_x=0.3, font_size="12sp")
        file_btn.bind(on_release=self.open_epub)
        file_row.add_widget(self.file_label)
        file_row.add_widget(file_btn)

        # [상단 2행 - 20%] 회차 수 표시
        info_row = BoxLayout(orientation="horizontal", size_hint_y=0.2)
        self.info_label = Label(text="회차 수: 0", halign="left", valign="middle")
        self.info_label.bind(size=lambda obj, val: setattr(obj, 'text_size', (val[0], None)))
        info_row.add_widget(self.info_label)

        # [상단 3행 - 40%] 진행도 및 목차 번역
        progress_row = BoxLayout(orientation="horizontal", size_hint_y=0.4, spacing=10)
        self.progress_label = Label(text="진행도: 없음", halign="left", valign="middle")
        self.progress_label.bind(size=lambda obj, val: setattr(obj, 'text_size', (val[0], None)))
        self.trans_btn = Button(text="목차 번역", size_hint_x=0.35, font_size="12sp")
        self.trans_btn.bind(on_release=self.confirm_and_translate)
        progress_row.add_widget(self.progress_label)
        progress_row.add_widget(self.trans_btn)

        # 상단 구조 적재
        top_frame.add_widget(file_row)
        top_frame.add_widget(info_row)
        top_frame.add_widget(progress_row)
        main_layout.add_widget(top_frame)

        # =========================================================================
        # ◼️ [중단 프레임 - 50%] 리스트 박스 영역
        # =========================================================================
        middle_frame = BoxLayout(orientation="vertical", size_hint_y=0.65)

        scroll_view = ScrollView(bar_width=10)
        self.list_container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=3)
        self.list_container.bind(minimum_height=self.list_container.setter('height'))
        scroll_view.add_widget(self.list_container)

        middle_frame.add_widget(scroll_view)
        main_layout.add_widget(middle_frame)

        # =========================================================================
        # ◼️ [하단 프레임 - 30%] 제어 및 연속 복사 버튼 영역
        # =========================================================================
        bottom_frame = BoxLayout(orientation="vertical", size_hint_y=0.25, spacing=8)

        # [하단 1행 - 20%] 현재 상태 메시지 라벨
        status_row = BoxLayout(orientation="horizontal", size_hint_y=0.3)
        self.current_title = Label(text="선택된 회차 없음", bold=True, halign="center", valign="middle")
        self.current_title.bind(size=lambda obj, val: setattr(obj, 'text_size', (val[0], None)))
        status_row.add_widget(self.current_title)

        # [하단 2행 - 40%] 회차 입력 제어행
        control_row = BoxLayout(orientation="horizontal", size_hint_y=0.2, spacing=8)
        self.chapter_entry = TextInput(
            hint_text="회차",
            multiline=False,
            input_filter='int',
            font_size="12sp",
            halign="center",
            padding=(0, 10, 0, 10),
            size_hint_x=0.35
        )
        copy_btn = Button(text="현재 회차 복사", size_hint_x=0.33, font_size="12sp")
        copy_btn.bind(on_release=lambda x: self.copy_selected_chapter())
        prev_btn = Button(text="이전 회차 복사", size_hint_x=0.32, font_size="12sp")
        prev_btn.bind(on_release=lambda x: self.copy_prev())

        control_row.add_widget(self.chapter_entry)
        control_row.add_widget(copy_btn)
        control_row.add_widget(prev_btn)

        # 회차 묶음 라인
        bundle_row = BoxLayout(orientation="horizontal", size_hint_y=0.2, spacing=8)
        bundle_label = Label(text="회차 묶음:", size_hint_x=0.2, font_size="12sp")
        self.bundle_entry = TextInput(
            text="1",
            multiline=False,
            input_filter='int',
            font_size="12sp",
            halign="center",
            padding=(0, 10, 0, 10),
            size_hint_x=0.2
        )

        # blank_label = Label(text="", size_hint_x=0.6)
        # bundle_row.add_widget(bundle_label)
        # bundle_row.add_widget(self.bundle_entry)
        # bundle_row.add_widget(blank_label)

        # 메모 추가
        memo_btn = Button(text="메모", size_hint_x=0.3, font_size="12sp", background_color=(0.3, 0.4, 0.5, 1))
        memo_btn.bind(on_release=self.open_memo_popup)

        memo_copy_btn = Button(text="메모 복사", size_hint_x=0.3, font_size="12sp", background_color=(0.25, 0.35, 0.45, 1))
        memo_copy_btn.bind(on_release=self.copy_memo_to_clipboard)

        bundle_row.add_widget(bundle_label)
        bundle_row.add_widget(self.bundle_entry)
        bundle_row.add_widget(memo_btn)
        bundle_row.add_widget(memo_copy_btn)

        spacer_line = Label(size_hint_y=None, height=2)

        # [하단 3행 - 40%] 대형 다음 회차 복사 버튼
        next_row = BoxLayout(
            orientation="horizontal",
            size_hint_y=0.4,
            spacing=30
        )

        paste_btn = Button(
            text="붙여넣기",
            font_size="19sp",
            bold=True,
            size_hint_x=0.35
        )
        paste_btn.bind(on_release=self.paste_clipboard)

        spacer = Label(size_hint_x=0.20)

        self.next_btn = Button(
            text="다음 회차 복사",
            font_size="19sp",
            bold=True,
            size_hint_x=0.45,
            background_color=(0.28, 0.28, 0.28, 1)
        )
        self.next_btn.bind(on_release=lambda x: self.copy_next())

        next_row.add_widget(paste_btn)
        next_row.add_widget(spacer)
        next_row.add_widget(self.next_btn)

        # 하단 구조 적재
        bottom_frame.add_widget(status_row)
        bottom_frame.add_widget(control_row)
        bottom_frame.add_widget(bundle_row)
        bottom_frame.add_widget(spacer_line)
        bottom_frame.add_widget(next_row)
        main_layout.add_widget(bottom_frame)

        # =========================================================
        # 2개의 탭 구성
        # =========================================================
        tab_panel = TabbedPanel(
            do_default_tab=False,
            tab_width=250,
            tab_height=80,
            
            background_image="",
            background_color=(0, 0, 0, 0)  
        )

        # ---------------------------------------------------------
        # 1번 탭 : 기존 EPUB 기능
        # ---------------------------------------------------------
        epub_tab = TabbedPanelItem(text="EPUB")
        epub_tab.add_widget(main_layout)

        # =========================================================
        # 2번 탭 : 누적 텍스트
        # =========================================================
        text_tab = TabbedPanelItem(
            text="텍스트"
        )

        text_tab.bind(on_release=self.on_text_tab_selected)

        # =========================================================
        # 텍스트 탭 전체 레이아웃
        # =========================================================
        text_tab_layout = BoxLayout(
            orientation="vertical",
            padding=(10, 10, 10, 20),
            spacing=5
        )

        # =========================================================
        # 상단 컨트롤 : 폰트 크기 + 검색창 + 검색 버튼
        # =========================================================
        top_control_layout = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=55,
            spacing=5
        )

        # ---------------------------------------------------------
        # 폰트 크기 라벨
        # ---------------------------------------------------------
        font_label = Label(
            text="폰트:",
            font_size="12sp",
            size_hint_x=0.12,
            size_hint_y=None,
            height=55
        )

        font_label.bind(
            size=lambda obj, val:
            setattr(obj, "text_size", (val[0], val[1]))
        )

        # ---------------------------------------------------------
        # progress.json에서 마지막으로 사용한 폰트 크기 불러오기
        #
        # _global.text_font_size가 없으면 14 사용
        # ---------------------------------------------------------
        saved_font_size = self.get_global_setting(
            "text_font_size",
            14
        )

        try:
            saved_font_size = int(saved_font_size)
        except Exception:
            saved_font_size = 14

        # 허용 범위 5 ~ 50
        saved_font_size = max(
            5,
            min(
                50,
                saved_font_size
            )
        )

        self.text_font_size = saved_font_size

        # ---------------------------------------------------------
        # 폰트 크기 Spinner
        # ---------------------------------------------------------
        font_spinner = Spinner(
            text=str(self.text_font_size),
            values=[str(i) for i in range(5, 51)],
            font_size="12sp",
            size_hint_x=0.13,
            size_hint_y=None,
            height=55
        )

        def on_font_size_change(spinner, text):

            try:
                font_size = int(text)
            except Exception:
                return

            # 허용 범위 제한
            font_size = max(
                5,
                min(
                    50,
                    font_size
                )
            )

            # 현재 앱의 폰트 크기 갱신
            self.text_font_size = font_size

            # -----------------------------------------------------
            # 현재 텍스트창에 즉시 적용
            # -----------------------------------------------------
            if (
                hasattr(self, "trans_text_input")
                and self.trans_text_input
            ):
                self.trans_text_input.font_size = (
                    f"{font_size}sp"
                )

            # -----------------------------------------------------
            # progress.json의 전역 설정에 저장
            # -----------------------------------------------------
            self.save_global_setting(
                "text_font_size",
                font_size
            )

        font_spinner.bind(
            text=on_font_size_change
        )

        # ---------------------------------------------------------
        # 검색창
        # ---------------------------------------------------------
        self.search_input = TextInput(
            hint_text="검색어 입력...",
            multiline=False,
            font_name="Roboto",
            font_size="12sp",
            size_hint_x=0.55,
            padding=(10, 10)
        )

        # Enter 키로 검색
        self.search_input.bind(
            on_text_validate=self.find_next_text
        )

        # ---------------------------------------------------------
        # 검색 버튼
        # ---------------------------------------------------------
        search_btn = Button(
            text="다음 찾기",
            font_size="13sp",
            bold=True,
            size_hint_x=0.20,
            background_color=(0.25, 0.35, 0.45, 1)
        )

        search_btn.bind(
            on_release=self.find_next_text
        )

        # ---------------------------------------------------------
        # 한 줄에 배치
        # ---------------------------------------------------------
        top_control_layout.add_widget(font_label)
        top_control_layout.add_widget(font_spinner)
        top_control_layout.add_widget(self.search_input)
        top_control_layout.add_widget(search_btn)

        # ---------------------------------------------------------
        # 3. 텍스트 본문 영역 (기존 텍스트창 및 스크롤바 조립)
        # ---------------------------------------------------------
        text_body = BoxLayout(orientation="horizontal", size_hint=(1, 1), spacing=4)
        
        self.trans_text_input = TextInput(
            text="",
            multiline=True,
            font_name="Roboto",
            font_size=f"{self.text_font_size}sp",
            padding=(10, 10),
            cursor_blink=False,
            size_hint=(1, 1)
        )
        """self.text_scrollbar = Slider(
            orientation="vertical", min=0, max=0, value=0, step=0,
            size_hint_x=None, width="30dp", cursor_size=("28dp", "45dp"),
            background_width="18dp", sensitivity="all"
        )"""
        self.text_scrollbar = Slider(
            orientation="vertical",
            min=0,
            max=0,
            value=0,
            step=0.001,
            size_hint_x=None,
            width="30dp",
            cursor_size=("28dp", "45dp"),
            background_width="18dp",
            sensitivity="all"
        )
        text_body.add_widget(self.trans_text_input)
        text_body.add_widget(self.text_scrollbar)

        self.trans_text_input.bind(
            scroll_y=self._on_trans_text_scroll,
            minimum_height=self._sync_scrollbar_from_textinput,
            height=self._sync_scrollbar_from_textinput,
            on_touch_move=self._on_trans_text_touch_move,
            on_touch_up=self._on_trans_text_touch_up
        )
        self.text_scrollbar.bind(value=self._sync_textinput_from_scrollbar)

        # =========================================================
        # 하단 이전/다음 페이지 버튼
        # =========================================================
        pg_control_layout = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=112,
            spacing=20,
            padding=(0, 0, 0, 0)
        )

        pg_up_btn = Button(
            text="이전 페이지",
            font_size="19sp",
            bold=True,
            size_hint_x=0.5,
            background_color=(0.28, 0.28, 0.28, 1)
        )

        pg_up_btn.bind(
            on_release=self.page_up_text
        )

        pg_dn_btn = Button(
            text="다음 페이지",
            font_size="19sp",
            bold=True,
            size_hint_x=0.5,
            background_color=(0.28, 0.28, 0.28, 1)
        )

        pg_dn_btn.bind(
            on_release=self.page_down_text
        )

        pg_control_layout.add_widget(pg_up_btn)
        pg_control_layout.add_widget(pg_dn_btn)

        # =========================================================
        # 텍스트 탭에 순서대로 추가
        # =========================================================
        text_tab_layout.add_widget(top_control_layout)
        text_tab_layout.add_widget(text_body)
        text_tab_layout.add_widget(pg_control_layout)

        # ---------------------------------------------------------
        # 하단 안전 여백
        #
        # Android 소프트키 영역과 페이지 버튼이 너무 가까워지는
        # 것을 방지하기 위한 비터치 영역
        # ---------------------------------------------------------
        """bottom_safe_area = Widget(
            size_hint_y=None,
            height=20
        )

        text_tab_layout.add_widget(bottom_safe_area)"""

        text_tab.add_widget(text_tab_layout)


        # =========================================================
        # 탭 패널에 추가
        # =========================================================
        tab_panel.add_widget(epub_tab)
        tab_panel.add_widget(text_tab)

        return tab_panel

    
    # =========================================================
    # ★ 검색 기능 (하이라이트 및 화면 정중앙 자동 스크롤)
    # =========================================================
    def find_next_text(self, *args):
        if not hasattr(self, "trans_text_input") or not hasattr(self, "search_input"):
            return
            
        query = self.search_input.text
        if not query:
            return
            
        text = self.trans_text_input.text
        if not text:
            return

        # 검색어가 바뀌었으면 인덱스를 초기화하고 처음부터 다시 찾음
        if getattr(self, '_last_search_query', '') != query:
            self._last_search_idx = 0
            self._last_search_query = query
        
        # 현재 인덱스부터 검색
        start_idx = text.find(query, self._last_search_idx)
        
        # 끝까지 찾았으면 처음(0)부터 다시 래핑(Wrapping) 검색
        if start_idx == -1:
            start_idx = text.find(query, 0)
            if start_idx == -1:
                return  # 문서에 일치하는 단어가 아예 없음

        end_idx = start_idx + len(query)
        
        old_suppress = self._suppress_scroll_save
        self._suppress_scroll_save = True

        try:
            # 1. 텍스트 하이라이트
            self.trans_text_input.select_text(
                start_idx,
                end_idx
            )

            # 2. 검색 결과 위치로 화면 이동
            col, row = self.trans_text_input.get_cursor_from_index(
                start_idx
            )

            line_height = self.trans_text_input.line_height
            target_y = row * line_height

            half_height = self.trans_text_input.height / 2

            max_scroll = max(
                0.0,
                float(
                    self.trans_text_input.minimum_height
                    - self.trans_text_input.height
                )
            )

            new_scroll_y = max(
                0.0,
                min(
                    max_scroll,
                    target_y - half_height
                )
            )

            self._set_trans_scroll_y(
                new_scroll_y,
                save=False
            )

        finally:
            self._suppress_scroll_save = old_suppress

    # =========================================================
    # ★ 페이지 업 / 다운 기능 (소프트키 방지용 대형 버튼 전용)
    # =========================================================
    def page_up_text(self, *args):

        if not hasattr(
            self,
            "trans_text_input"
        ):
            return

        ti = self.trans_text_input

        new_scroll = max(
            0.0,
            ti.scroll_y - (ti.height * 0.9)
        )

        self._set_trans_scroll_y(
            new_scroll,
            save=True
        )


    def page_down_text(self, *args):

        if not hasattr(
            self,
            "trans_text_input"
        ):
            return

        ti = self.trans_text_input

        max_scroll = max(
            0.0,
            float(
                ti.minimum_height - ti.height
            )
        )

        new_scroll = min(
            max_scroll,
            ti.scroll_y + (ti.height * 0.9)
        )

        self._set_trans_scroll_y(
            new_scroll,
            save=True
        )

    def _set_trans_scroll_y(self, value, save=False):

        if not hasattr(
            self,
            "trans_text_input"
        ):
            return

        ti = self.trans_text_input

        try:

            value = float(value)

        except Exception:

            value = 0.0

        max_scroll = max(
            0.0,
            float(
                ti.minimum_height - ti.height
            )
        )

        value = max(
            0.0,
            min(
                max_scroll,
                value
            )
        )

        old_suppress = (
            self._suppress_scroll_save
        )

        if not save:
            self._suppress_scroll_save = True

        try:

            ti.scroll_y = value

            try:
                ti._trigger_update_graphics()
            except Exception:
                pass

        finally:

            self._suppress_scroll_save = (
                old_suppress
            )

        self._sync_scrollbar_from_textinput()

        # ---------------------------------------------------------
        # 이전/다음 페이지 버튼 또는 스크롤바 등
        # 명시적으로 사용자 동작으로 호출된 경우
        # ---------------------------------------------------------
        if save:

            self.saved_scroll_y = float(
                ti.scroll_y
            )

            self._schedule_trans_progress_save()

    # =========================================================
    # TextInput → 스크롤바
    # =========================================================
    def _sync_scrollbar_from_textinput(self, *args):

        if not hasattr(self, "trans_text_input"):
            return

        if not hasattr(self, "text_scrollbar"):
            return

        ti = self.trans_text_input
        sb = self.text_scrollbar

        max_scroll = max(
            0.0,
            float(ti.minimum_height - ti.height)
        )

        self._scrollbar_syncing = True

        try:
            sb.max = max_scroll
            sb.value = max(
                0.0,
                min(
                    max_scroll,
                    max_scroll - ti.scroll_y
                )
            )

        finally:
            self._scrollbar_syncing = False

    # =========================================================
    # 텍스트 읽기 위치 저장
    # =========================================================
    def _on_trans_text_scroll(self, *args):
        """
        TextInput.scroll_y 변경 감지.

        저장되는 경우:
            1. 사용자의 실제 터치 스크롤
            2. 스크롤바를 사용자가 움직인 경우
            3. 이전/다음 페이지 버튼

        저장되지 않는 경우:
            - EPUB 로딩
            - trans.txt 로딩
            - 텍스트 삽입
            - 검색 이동
            - 레이아웃 변경
            - Kivy 내부적인 scroll_y 변경
        """

        if not hasattr(
            self,
            "trans_text_input"
        ):
            return

        self._sync_scrollbar_from_textinput()

        # ---------------------------------------------------------
        # 프로그램이 의도적으로 변경한 경우
        # ---------------------------------------------------------
        if self._suppress_scroll_save:
            return

        # ---------------------------------------------------------
        # 사용자의 실제 터치/스크롤 동작이 아닌 경우
        # 저장하지 않는다.
        # ---------------------------------------------------------
        if not getattr(
            self,
            "_user_scroll_action",
            False
        ):
            return

        # ---------------------------------------------------------
        # 실제 사용자 스크롤 위치 저장
        # ---------------------------------------------------------
        try:

            self.saved_scroll_y = float(
                self.trans_text_input.scroll_y
            )

        except Exception:

            return

        self._schedule_trans_progress_save()

    def _on_trans_text_touch_move(
        self,
        instance,
        touch
        ):
        """
        TextInput에서 실제 손가락/마우스 이동이 발생했음을 표시한다.

        이후 발생하는 scroll_y 변경만 사용자 스크롤로 인정한다.
        """

        self._user_scroll_action = True

        return False


    def _on_trans_text_touch_up(
        self,
        instance,
        touch
        ):
        """
        터치가 끝나면 사용자 스크롤 상태를 해제한다.
        """

        # scroll_y 이벤트 처리가 끝난 뒤 해제되도록
        # 한 프레임 뒤에 False 처리한다.
        self._user_scroll_action = False

        return False

    def _schedule_trans_progress_save(self):

        if not self.current_filename:
            return

        if not self.trans_file_path:
            return

        if getattr(self, "_trans_progress_save_event", None):

            try:
                self._trans_progress_save_event.cancel()
            except Exception:
                pass

        self._trans_progress_save_event = Clock.schedule_once(
            self._save_trans_position_delayed,
            0.5
        )


    def _save_trans_position_delayed(self, dt):

        self._trans_progress_save_event = None

        if not self.current_filename:
            return

        if not self.trans_file_path:
            return

        ti = self.trans_text_input

        if not ti:
            return

        # ---------------------------------------------------------
        # 사용자의 실제 스크롤로 이미 갱신된
        # self.saved_scroll_y를 사용한다.
        #
        # 여기서 ti.scroll_y를 새로 읽어
        # saved_scroll_y를 덮어쓰지 않는다.
        # ---------------------------------------------------------

        try:

            self.trans_read_position = (
                ti.get_index_from_cursor(
                    ti.cursor
                )
            )

        except Exception:

            self.trans_read_position = 0

        # ---------------------------------------------------------
        # ★ scroll_y 저장을 명시적으로 허용
        # ---------------------------------------------------------
        self.save_progress(
            save_scroll=True
        )


    # =========================================================
    # 스크롤바 → TextInput
    # =========================================================
    def _sync_textinput_from_scrollbar(self, instance, value):

        if getattr(self, "_scrollbar_syncing", False):
            return

        if not hasattr(self, "trans_text_input"):
            return

        ti = self.trans_text_input

        max_scroll = max(
            0.0,
            float(ti.minimum_height - ti.height)
        )

        target_scroll = max_scroll - float(value)

        # 슬라이더는 명백한 사용자 스크롤
        self._set_trans_scroll_y(
            target_scroll,
            save=False
        )

    # =========================================================
    # 텍스트창 비우기
    # =========================================================
    def clear_text_viewer(self):

        if getattr(self, "_load_event", None):

            try:
                self._load_event.cancel()
            except Exception:
                pass

            self._load_event = None

        if not hasattr(self, "trans_text_input"):
            return

        ti = self.trans_text_input

        was_readonly = ti.readonly

        old_suppress = self._suppress_scroll_save
        self._suppress_scroll_save = True

        try:

            ti.readonly = False
            ti.text = ""
            ti.readonly = was_readonly

            # 화면 초기화만 한다.
            # 저장값은 여기서 건드리지 않는다.
            ti.scroll_y = 0.0

        finally:

            self._suppress_scroll_save = old_suppress

        self._sync_scrollbar_from_textinput()

        try:
            ti._trigger_update_graphics()
        except Exception:
            pass

    def _get_trans_file_path(self):
        if not self.epub_path:
            return None

        base_path = os.path.splitext(self.epub_path)[0]
        return base_path + "_trans.txt"
    
    def _load_trans_text(self):

        path = self._get_trans_file_path()

        if not path:
            return

        self.trans_file_path = path

        if not self.trans_text_input:
            return

        if not os.path.exists(path):

            # -----------------------------------------------------
            # trans 파일 자체가 없으면 아직 초기화되지 않은 상태
            # -----------------------------------------------------
            self.trans_initialized = False
            self.saved_scroll_y = 0.0

            self.clear_text_viewer()

            return

        try:

            with open(
                path,
                "r",
                encoding="utf-8"
            ) as f:

                text = f.read()

            # -----------------------------------------------------
            # progress.json의 현재 상태 확인
            # -----------------------------------------------------
            progress_data = (
                self.get_current_progress()
            )

            trans_data = progress_data.get(
                "trans",
                {}
            )

            if not isinstance(
                trans_data,
                dict
            ):
                trans_data = {}

            saved_filename = (
                trans_data.get(
                    "filename",
                    ""
                )
            )

            # -----------------------------------------------------
            # 이미 load_epub()에서 판정된
            # trans_initialized 상태를 사용한다.
            # -----------------------------------------------------
            has_saved_position = (
                self.trans_initialized
                and
                saved_filename
                == os.path.basename(path)
            )

            if has_saved_position:

                saved_scroll_y = (
                    self.saved_scroll_y
                )

            else:

                saved_scroll_y = 0.0

            self.load_large_text(
                text,
                chunk_size=2000,
                on_complete=lambda:
                self._restore_trans_position(
                    saved_scroll_y,
                    has_saved_position
                )
            )

        except Exception as e:

            print(
                "trans 텍스트 로드 실패:",
                e
            )

            self.clear_text_viewer()

    # =========================================================
    # 텍스트 추가
    #
    # 절대로
    # self.trans_text_input.text += new_text
    #
    # 형태로 사용하지 않는다.
    # =========================================================
    def append_text_to_viewer(self, new_text, from_undo=True):

        if not new_text:
            return

        if not hasattr(self, "trans_text_input"):
            return

        ti = self.trans_text_input

        was_readonly = ti.readonly

        # =====================================================
        # 텍스트 삽입 과정에서 Kivy가 자동으로 scroll_y를
        # 변경할 수 있다.
        #
        # 하지만 이것은 사용자 스크롤이 아니다.
        # =====================================================
        old_suppress = self._suppress_scroll_save
        self._suppress_scroll_save = True

        try:

            ti.readonly = False

            # 텍스트 맨 끝에 추가
            ti.cursor = ti.get_cursor_from_index(
                len(ti.text)
            )

            ti.insert_text(
                new_text,
                from_undo=from_undo
            )

            ti.readonly = was_readonly

        finally:

            self._suppress_scroll_save = old_suppress

    # =========================================================
    # 텍스트창 맨 아래로 이동
    # =========================================================
    def scroll_text_viewer_to_end(self):

        if not hasattr(self, "trans_text_input"):
            return

        ti = self.trans_text_input

        max_scroll = max(
            0,
            ti.minimum_height - ti.height
        )

        self._set_trans_scroll_y(max_scroll)

        try:
            ti._trigger_update_graphics()
        except Exception:
            pass

        self._sync_scrollbar_from_textinput()

    # =========================================================
    # 대용량 텍스트 로딩 시작
    # =========================================================
    def load_large_text(
        self,
        full_text,
        chunk_size=2000,
        on_complete=None
        ):

        self.clear_text_viewer()

        if not full_text:

            if on_complete:
                on_complete()

            return

        self._load_buffer = full_text
        self._load_pos = 0
        self._load_chunk_size = max(
            500,
            chunk_size
        )

        self._load_on_complete = on_complete

        self._load_event = Clock.schedule_interval(
            self._load_next_chunk,
            0
        )


    # =========================================================
    # 대용량 텍스트 chunk 처리
    # =========================================================
    def _load_next_chunk(self, dt):

        buf = self._load_buffer
        pos = self._load_pos

        end = pos + self._load_chunk_size

        chunk = buf[pos:end]

        # -----------------------------------------------------
        # 로딩 완료
        # -----------------------------------------------------
        if not chunk:

            if self._load_event:

                try:
                    self._load_event.cancel()
                except Exception:
                    pass

            self._load_event = None

            self._sync_scrollbar_from_textinput()

            if self._load_on_complete:

                callback = self._load_on_complete

                self._load_on_complete = None

                callback()

            return

        # -----------------------------------------------------
        # 이번 chunk만 추가
        # -----------------------------------------------------
        self.append_text_to_viewer(
            chunk,
            from_undo=True
        )

        self._load_pos = end

    # =========================================================
    # trans.txt 읽기 위치 복원
    # =========================================================
    def _restore_trans_position(
        self,
        saved_scroll_y,
        has_saved_position
        ):

        ti = self.trans_text_input

        if not ti:
            return

        self._suppress_scroll_save = True

        try:

            if has_saved_position:

                # -------------------------------------------------
                # 기존 정상 저장 위치 복원
                # -------------------------------------------------
                target_scroll = float(
                    saved_scroll_y
                )

                max_scroll = max(
                    0.0,
                    float(
                        ti.minimum_height - ti.height
                    )
                )

                target_scroll = max(
                    0.0,
                    min(
                        max_scroll,
                        target_scroll
                    )
                )

                self._set_trans_scroll_y(
                    target_scroll,
                    save=False
                )

                # 기존 저장값 그대로 유지
                self.saved_scroll_y = (
                    target_scroll
                )

            else:

                # -------------------------------------------------
                # 정상적인 저장 위치가 없는 경우
                #
                # 화면 위치만 0으로 초기화한다.
                #
                # ★ progress.json에는 아무것도 저장하지 않는다.
                # ★ saved_scroll_y도 새 위치로 저장하지 않는다.
                # -------------------------------------------------
                self._set_trans_scroll_y(
                    0.0,
                    save=False
                )

                self.saved_scroll_y = 0.0

            try:
                ti._trigger_update_graphics()
            except Exception:
                pass

            self._sync_scrollbar_from_textinput()

        finally:

            self._suppress_scroll_save = False


    def _restore_trans_position_delayed(
        self,
        saved_scroll_y,
        has_saved_position
        ):

        ti = self.trans_text_input

        if not ti:
            return

        self._suppress_scroll_save = True

        try:

            max_scroll = max(
                0.0,
                float(
                    ti.minimum_height - ti.height
                )
            )

            if has_saved_position:

                target_scroll = max(
                    0.0,
                    min(
                        max_scroll,
                        float(saved_scroll_y)
                    )
                )

                self._set_trans_scroll_y(
                    target_scroll,
                    save=False
                )

                self.saved_scroll_y = (
                    target_scroll
                )

            else:

                # -------------------------------------------------
                # 저장 위치가 없는 경우 화면만 맨 위
                # -------------------------------------------------
                self._set_trans_scroll_y(
                    0.0,
                    save=False
                )

                self.saved_scroll_y = 0.0

            try:
                ti._trigger_update_graphics()
            except Exception:
                pass

            self._sync_scrollbar_from_textinput()

        finally:

            self._suppress_scroll_save = False

    def on_text_tab_selected(self, *args):

        if not self.trans_text_input:
            return

        if not self.trans_file_path:
            return

        if not os.path.exists(
            self.trans_file_path
        ):
            return

        # ---------------------------------------------------------
        # 정상적인 trans 상태가 아니면 복원하지 않는다.
        # ---------------------------------------------------------
        if not self.trans_initialized:
            return

        progress_data = (
            self.get_current_progress()
        )

        trans_data = progress_data.get(
            "trans",
            {}
        )

        if not isinstance(
            trans_data,
            dict
        ):
            return

        saved_filename = (
            trans_data.get(
                "filename",
                ""
            )
        )

        if saved_filename != os.path.basename(
            self.trans_file_path
        ):
            return

        if "scroll_y" not in trans_data:
            return

        try:

            saved_scroll_y = float(
                trans_data["scroll_y"]
            )

        except Exception:

            return

        self.saved_scroll_y = (
            saved_scroll_y
        )

        # 즉시 복원
        self._restore_trans_position(
            saved_scroll_y,
            True
        )

    def paste_clipboard(self, *args):

        if not self.epub_path:
            self.current_title.text = "먼저 EPUB 파일을 선택하세요."
            return

        if not self.trans_file_path:
            self.trans_file_path = self._get_trans_file_path()

        if not self.trans_file_path:
            return

        try:

            from kivy.core.clipboard import Clipboard

            text = Clipboard.paste()

            if not text:
                self.current_title.text = (
                    "클립보드에 텍스트가 없습니다."
                )
                return

            # 줄바꿈 형식 통일
            text = text.replace('\r\n', '\n').replace('\r', '\n')

            # 연속된 빈 줄을 최대 1줄만 유지
            text = re.sub(
                r'\n[ \t]*\n(?:[ \t]*\n)+',
                '\n\n',
                text
            )

            ti = self.trans_text_input

            # =====================================================
            # 1. 붙여넣기 직전의 실제 스크롤 위치 저장
            #
            # insert_text() 과정에서 Kivy가 자동으로
            # 맨 아래로 이동할 수 있으므로 미리 기억한다.
            # =====================================================

            try:
                old_scroll_y = float(ti.scroll_y)
            except Exception:
                old_scroll_y = float(self.saved_scroll_y)

            # =====================================================
            # 2. 최초 trans 상태인지 확인
            # =====================================================

            if not self.trans_initialized:

                progress = self.load_progress()

                epub_progress = progress.get(
                    self.current_filename,
                    {}
                )

                if not isinstance(epub_progress, dict):
                    epub_progress = {}

                # 기존 chapter 유지
                if self.current_index >= 0:
                    epub_progress["chapter"] = (
                        self.current_index + 1
                    )

                # bundle 유지
                epub_progress["bundle"] = (
                    self.get_bundle_size()
                )

                # 최초 trans 구조 생성
                epub_progress["trans"] = {
                    "filename": os.path.basename(
                        self.trans_file_path
                    ),
                    "scroll_y": 0
                }

                progress[self.current_filename] = (
                    epub_progress
                )

                target_path = self.get_progress_file_path()

                os.makedirs(
                    os.path.dirname(target_path),
                    exist_ok=True
                )

                with open(
                    target_path,
                    "w",
                    encoding="utf-8"
                ) as f:

                    json.dump(
                        progress,
                        f,
                        ensure_ascii=False,
                        indent=2
                    )

                self.saved_scroll_y = 0.0
                self.trans_initialized = True

                print(
                    "[TRANS] 최초 붙여넣기 → "
                    "trans.filename / scroll_y=0 생성"
                )

            # =====================================================
            # 3. 화면에 텍스트 추가
            #
            # 여기서 Kivy가 scroll_y를 변경할 수 있다.
            # =====================================================

            if ti.text:

                self.append_text_to_viewer(
                    "\n\n" + text
                )

            else:

                self.append_text_to_viewer(
                    text
                )

            # =====================================================
            # 4. 실제 _trans.txt에 텍스트 추가
            # =====================================================

            file_exists = os.path.exists(
                self.trans_file_path
            )

            file_has_content = (
                file_exists
                and os.path.getsize(
                    self.trans_file_path
                ) > 0
            )

            with open(
                self.trans_file_path,
                "a",
                encoding="utf-8"
            ) as f:

                if file_has_content:
                    f.write("\n\n")

                f.write(text)

            # =====================================================
            # 5. 붙여넣기 전 스크롤 위치 즉시 복원
            #
            # Clock.schedule_once()를 사용하지 않는다.
            # =====================================================

            old_suppress = getattr(
                self,
                "_suppress_scroll_save",
                False
            )

            self._suppress_scroll_save = True

            try:

                max_scroll = max(
                    0.0,
                    float(
                        ti.minimum_height - ti.height
                    )
                )

                target_scroll = max(
                    0.0,
                    min(
                        max_scroll,
                        old_scroll_y
                    )
                )

                self._set_trans_scroll_y(
                    target_scroll,
                    save=False
                )

                self.saved_scroll_y = target_scroll

                try:
                    ti._trigger_update_graphics()
                except Exception:
                    pass

                try:
                    self._sync_scrollbar_from_textinput()
                except Exception:
                    pass

            finally:

                self._suppress_scroll_save = old_suppress

            # =====================================================
            # 6. 완료
            # =====================================================

            self.current_title.text = (
                "붙여넣기 및 자동 저장 완료"
            )

        except Exception as e:

            print(
                "붙여넣기 실패:",
                e
            )

            self.current_title.text = (
                f"붙여넣기 실패: {e}"
            )

    def open_memo_popup(self, *args):
        content = BoxLayout(orientation="vertical", padding=10, spacing=10)
        memo_input = TextInput(text=self.memo_text, multiline=True, font_name="Roboto", font_size="14sp")

        btn_layout = BoxLayout(orientation="horizontal", size_hint_y=0.1, spacing=5)
        close_btn = Button(text="저장 후 닫기", font_size="14sp", bold=True)

        content.add_widget(memo_input)
        content.add_widget(btn_layout)
        btn_layout.add_widget(close_btn)

        popup = Popup(title="메모장", content=content, size_hint=(0.95, 0.95), auto_dismiss=False)

        # 💡 닫기 버튼을 누르면 변수 저장과 동시에 파일 쓰기(영구 저장)를 수행합니다.
        def save_and_close(*args):
            self.memo_text = memo_input.text
            try:
                with open(self.get_memo_file_path(), "w", encoding="utf-8") as f:
                    f.write(self.memo_text)
                self.current_title.text = "상태: 메모가 안전하게 자동 저장되었습니다."
            except Exception as e:
                print("메모 자동 저장 실패:", e)
            popup.dismiss()

        close_btn.bind(on_release=save_and_close)
        popup.open()

    def copy_memo_to_clipboard(self, *args):
        if self.memo_text.strip():
            self.copy_to_clipboard(self.memo_text)
            self.current_title.text = "상태: 메모장 전체 내용 복사 완료!"
        else:
            self.current_title.text = "상태: 메모장이 비어 있습니다."

    def on_window_close(self, *args):
        # 💡 X 버튼을 눌렀을 때 즉시 꺼지는 것을 방지하고 팝업을 띄웁니다.
        self.show_exit_dialog()
        return True  # True를 반환해야 창 닫기 이벤트가 일시정지됩니다.

    def on_hardware_back(self, window, key, *args):
        if key == 27:
            self.show_exit_dialog()
            return True
        return False

    def show_exit_dialog(self):
        content = BoxLayout(orientation="vertical", padding=15, spacing=15)

        content.add_widget(Label(
            text="프로그램을 종료하시겠습니까?\n종료 시 현재 진행도가 자동 저장됩니다.",
            color=(1, 1, 1, 1),
            halign="center",
            valign="middle"
        ))

        btn_layout = BoxLayout(orientation="horizontal", spacing=12, size_hint_y=None, height=100)

        cancel_btn = Button(text="취소", font_size="16sp", bold=True, background_color=(0.4, 0.4, 0.4, 1))
        exit_btn = Button(text="종료", font_size="16sp", bold=True, background_color=(0.25, 0.25, 0.25, 1))

        btn_layout.add_widget(cancel_btn)
        btn_layout.add_widget(exit_btn)
        content.add_widget(btn_layout)

        popup = Popup(title="종료 확인", content=content, size_hint=(0.85, 0.4), auto_dismiss=False)

        # 💡 [보완] 취소 클릭 시 팝업을 닫고, 시스템에게 종료 취소 신호(restore)를 확실히 전달
        cancel_btn.bind(on_release=lambda x: [popup.dismiss(), self.cancel_exit()])

        exit_btn.bind(on_release=lambda x: [popup.dismiss(), self.execute_exit()])
        popup.open()

    def cancel_exit(self):
        # 윈도우 닫기 요청을 취소하고 원래 상태로 안전하게 복원합니다.
        pass

    def execute_exit(self):
        try:

            # -------------------------------------------------
            # 예약된 trans 저장 이벤트가 있다면 취소
            # -------------------------------------------------
            if getattr(
                self,
                "_trans_progress_save_event",
                None
            ):

                try:
                    self._trans_progress_save_event.cancel()
                except Exception:
                    pass

                self._trans_progress_save_event = None

            # -------------------------------------------------
            # 현재 EPUB의 진행도 최종 저장
            # -------------------------------------------------
            if self.current_filename and self.current_index != -1:

                # 현재 실제 스크롤 위치도 마지막으로 반영
                if (
                    self.trans_text_input
                    and self.trans_initialized
                    and self.trans_file_path
                    and os.path.exists(self.trans_file_path)
                ):

                    try:
                        self.saved_scroll_y = float(
                            self.trans_text_input.scroll_y
                        )
                    except Exception:
                        pass

                    self.save_progress(
                        save_scroll=True
                    )

                else:

                    self.save_progress()

        except Exception as e:

            print(
                "종료 전 최종 자동 저장 실패:",
                e
            )

        self.stop()
        sys.exit(0)

    def open_epub(self, *args):
        if platform == "android":
            from kivy.uix.filechooser import FileChooserListView
            from android.storage import primary_external_storage_path
            init_path = primary_external_storage_path()

            # 💡 호출한 경로를 FileChooser에 적용 (명시적 재할당)
            # target_path = self.get_last_path()

            # 💡 마지막 경로 호출
            # init_path = self.get_last_path()

            # 💡 [구조 혁신] 순정 다크 테마 유지 + 글자만 화이트로 강제 오버라이드
            # 탐색기 내부의 파일명, 폴더명 및 상단 헤더(Name, Size) 글자를 모두 밝은 색으로 고정합니다.
            Builder.load_string("""
<FileChooserListView>:
    # 배경 캔버스를 건드리지 않고 순정 상태의 다크 톤을 유지합니다.
<FileChooserLabel>:
    color: 1, 1, 1, 1  # 파일명 및 폴더명을 완전한 흰색(White)으로 락인
<Label>:
    # 탐색기 헤더(Name, Size) 영역 등의 기본 라벨도 어두운 팝업 안에서는 흰색으로 보이도록 매칭
    color: 0.95, 0.95, 0.95, 1 
""")

            content = BoxLayout(orientation='vertical', padding=10, spacing=10)

            # 만약 경로가 바뀌었는데도 이전 경로가 뜬다면,
            # 아래 명령어로 강제 이동을 시도합니다.
            # filechooser.path = target_path

            filechooser = FileChooserListView(path=init_path, filters=['*.epub'])

            # 여기서 path를 확실하게 넘겨줍니다.
            # filechooser = FileChooserListView(path=target_path, filters=['*.epub'])

            content.add_widget(filechooser)

            # 하단 버튼 바 (선택 완료 / 취소 버튼)
            btn_bar = BoxLayout(orientation="horizontal", spacing=12, size_hint_y=None, height=110)
            cancel_btn = Button(text="취소", font_size="16sp", bold=True, background_color=(0.35, 0.35, 0.35, 1))
            select_btn = Button(text="선택 완료", font_size="16sp", bold=True, background_color=(0.2, 0.2, 0.2, 1))

            btn_bar.add_widget(cancel_btn)
            btn_bar.add_widget(select_btn)
            content.add_widget(btn_bar)

            popup = Popup(title="EPUB 파일 선택", content=content, size_hint=(0.95, 0.95), auto_dismiss=False)

            cancel_btn.bind(on_release=popup.dismiss)
            select_btn.bind(on_release=lambda x: self.android_file_selected(filechooser.selection, popup))

            popup.open()
        else:
            # PC 환경 분기 (기존 유지)
            try:
                from tkinter import filedialog, Tk
                init_path = os.path.expanduser("~")
                root = Tk()
                root.withdraw()
                path = filedialog.askopenfilename(initialdir=init_path, filetypes=[("EPUB Files", "*.epub")])
                root.destroy()
                if path:
                    self.load_epub(path)
            except Exception as e:
                print("PC 파일 탐색기 구동 실패:", e)

    def android_file_selected(self, selection, popup):
        # selection 리스트에 단 하나라도 선택된 파일 패스가 있다면 즉시 파싱 프로세스 진입
        if selection and len(selection) > 0:
            target_path = selection[0]
            try:
                self.load_epub(target_path)
            except Exception as e:
                print("안드로이드 EPUB 로드 실패:", e)
            popup.dismiss()

    def refresh_listbox(self, title_map):
        self.list_container.clear_widgets()
        for i in range(len(self.chapters)):
            item_text = f" {i + 1}. {title_map.get(i, self.chapters[i]['title'])}"
            # 순수 Kivy 버튼을 리스트 아이템으로 개량 (KivyMD 의존 완전 제거)
            item = Button(
                text=item_text,
                size_hint_y=None,
                size_hint_x=1,
                height=45,
                halign="left",
                valign="middle",
                shorten=True,
                shorten_from='right',
                background_normal='',
                background_color=(1, 1, 1, 1) if i % 2 == 0 else (0.92, 0.94, 0.96, 1),  # 줄무늬 디자인
                color=(0.1, 0.1, 0.1, 1)
                # clip=True
            )
            item.bind(size=lambda obj, val: setattr(obj, 'text_size', (val[0] - 20, None)))
            item.bind(on_release=lambda x, idx=i: self.on_select_item(idx))
            self.list_container.add_widget(item)

    def on_select_item(self, index):
        self.current_index = index

        # 💡 현재 번역 상태에 따라 제목을 선택하도록 로직 변경
        if self.is_translated and index in self.translated_titles:
            display_title = self.translated_titles[index]
        else:
            display_title = self.chapters[index]['title']

        # 💡 리스트 박스 상의 넘버링(1부터 시작) 계산
        display_num = index + 1

        # 💡 상태표시 라벨에 넘버링을 포함하여 가독성 높게 표시
        # 예시 결과: "선택된 회차: [1] 제1화 시작하며" 또는 "선택된 회차: 1. 제1화 시작하며"
        self.current_title.text = f"선택된 회차: [{display_num}] {display_title}"

        self.chapter_entry.text = str(display_num)

    def select_list_item(self, index):
        self.on_select_item(index)
        count = len(self.chapters)
        self.progress_label.text = f"진행도: {index + 1}/{count}"

    def confirm_and_translate(self, *args):
        # 1. 만약 목록에 데이터가 아예 없다면 작동 안 함
        if not self.chapters:
            return

        # 2. [현재 번역 목차를 보고 있는 상태] -> 원문 목차로 전환
        if self.is_translated:
            # 💡 [수정] 빈 딕셔너리({}) 대신 원문 제목 리스트를 정상적으로 주입
            self.refresh_listbox({i: ch['title'] for i, ch in enumerate(self.chapters)})
            self.is_translated = False  # 리스트박스 상태를 원문 상태로 변경
            self.trans_btn.text = "번역 목차"  # 💡 버튼은 다시 번역본으로 갈 수 있게 토글
            return

        # 3. [현재 원문 목차를 보고 있는 상태] -> 번역 목차로 전환 시도
        # 이미 이전에 번역해 둔 데이터(캐시 등)가 내부에 존재하는 경우 (구글 API 호출 안 함)
        if self.translated_titles:
            self.refresh_listbox(self.translated_titles)
            self.is_translated = True  # 리스트박스 상태를 번역 상태로 변경
            self.trans_btn.text = "원문 목차"  # 💡 버튼은 다시 원문으로 갈 수 있게 토글
            return

        # 4. [완전 최초 로딩 상태] 내부에 번역 데이터가 아예 없을 때만 Kivy 전용 팝업 출력
        total_count = len(self.chapters)

        content = BoxLayout(orientation="vertical", padding=10, spacing=10)
        content.add_widget(Label(
            text=f"현재 문서의 목차는 총 {total_count}개입니다.\n\n50화 단위로 제목을 번역합니다.\n\n인터넷 연결로 작업을 시작할까요?",
            color=(1, 1, 1, 1),
            halign="center"
        ))

        btn_layout = BoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=100)
        cancel_btn = Button(text="취소")
        go_btn = Button(text="번역 시작")
        btn_layout.add_widget(cancel_btn)
        btn_layout.add_widget(go_btn)
        content.add_widget(btn_layout)

        popup = Popup(title="목차 번역 안내", content=content, size_hint=(0.85, 0.35), auto_dismiss=False)
        cancel_btn.bind(on_release=popup.dismiss)
        go_btn.bind(on_release=lambda x: [popup.dismiss(), self.translate_chapter_list()])
        popup.open()

    def update_status_label(self, index):
        # 💡 [수정] index를 int로 명시하여 안전하게 변환
        target_idx = int(index)

        # 현재 번역 상태에 따라 제목을 선택
        if self.is_translated and target_idx in self.translated_titles:
            display_title = self.translated_titles[target_idx]
        else:
            display_title = self.chapters[target_idx]['title']

        self.current_title.text = f"복사 완료: {display_title}"

    def _initialize_trans_state(self):
        """
        현재 EPUB의 progress.json 상태를 한 번 검사하여
        self.trans_initialized 와 self.saved_scroll_y를 결정한다.

        trans_initialized = True 조건:

        1. EPUB 항목 존재
        2. trans 항목 존재
        3. trans.filename 존재
        4. 해당 _trans.txt 실제 파일 존재
        5. trans.scroll_y 항목 존재 + 값이 유효함

        위 조건 중 하나라도 실패하면 False.

        중요:
        이 함수는 기존 scroll_y를 절대로 수정하지 않는다.
        """

        self.trans_initialized = False
        self.saved_scroll_y = 0.0

        if not self.current_filename:
            return

        # ---------------------------------------------------------
        # progress.json 조회
        # ---------------------------------------------------------
        progress = self.load_progress()

        epub_data = progress.get(
            self.current_filename
        )

        # 1. EPUB 항목 자체가 없음
        if not isinstance(epub_data, dict):
            return

        # 2. trans 항목이 없음
        trans_data = epub_data.get("trans")

        if not isinstance(trans_data, dict):
            return

        # 3. trans.filename 없음
        filename = trans_data.get("filename")

        if not filename:
            return

        # ---------------------------------------------------------
        # 실제 _trans.txt 경로
        #
        # progress.json의 filename은 파일명만 사용한다.
        # 실제 파일은 EPUB과 같은 위치의 _trans.txt를 사용한다.
        # ---------------------------------------------------------
        trans_path = self._get_trans_file_path()

        if not trans_path:
            return

        # 4. 실제 _trans.txt 파일 없음
        if not os.path.exists(trans_path):
            return

        # ---------------------------------------------------------
        # filename도 실제 파일과 일치해야 한다.
        # ---------------------------------------------------------
        if filename != os.path.basename(trans_path):
            return

        # 5. scroll_y 항목 자체가 없음
        if "scroll_y" not in trans_data:
            return

        scroll_value = trans_data.get("scroll_y")

        # 값이 None 또는 빈 문자열이면 실패
        if scroll_value is None or scroll_value == "":
            return

        try:
            scroll_value = float(scroll_value)
        except Exception:
            return

        # NaN / Infinity 방지
        if not (float("-inf") < scroll_value < float("inf")):
            return

        # ---------------------------------------------------------
        # 모든 조건 통과
        # ---------------------------------------------------------
        self.saved_scroll_y = scroll_value
        self.trans_initialized = True

        print(
            f"[TRANS] 기존 trans 상태 확인 완료: "
            f"scroll_y={self.saved_scroll_y}"
        )

    def load_progress(self):
        # 💡 동적 경로를 호출하여 읽기
        target_path = self.get_progress_file_path()
        if not os.path.exists(target_path):
            return {}
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}

    def get_global_setting(self, key, default=None):
        """
        progress.json의 최상위 _global 영역에서
        전역 설정값을 가져온다.

        예:
        {
            "_global": {
                "text_font_size": 18
            },
            "소설.epub": {
                ...
            }
        }

        _global 또는 해당 설정값이 없으면
        전달받은 default 값을 반환한다.
        """

        progress = self.load_progress()

        global_data = progress.get(
            "_global",
            {}
        )

        if not isinstance(global_data, dict):
            return default

        return global_data.get(
            key,
            default
        )


    def save_global_setting(self, key, value):
        """
        progress.json의 최상위 _global 영역에
        전역 설정값을 저장한다.

        기존 EPUB별 진행도는 그대로 유지한다.
        """

        target_path = self.get_progress_file_path()

        progress = self.load_progress()

        global_data = progress.get(
            "_global",
            {}
        )

        if not isinstance(global_data, dict):
            global_data = {}

        global_data[key] = value

        progress["_global"] = global_data

        try:

            os.makedirs(
                os.path.dirname(target_path),
                exist_ok=True
            )

            with open(
                target_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    progress,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print(
                f"[GLOBAL] 설정 저장 완료: "
                f"{key}={value}"
            )

        except Exception as e:

            print(
                f"[GLOBAL] 설정 저장 실패: {e}"
            )

    def get_current_progress(self):

        if not self.current_filename:
            return {}

        progress = self.load_progress()

        data = progress.get(
            self.current_filename,
            {}
        )

        # 구버전 progress.json 호환
        if isinstance(data, int):
            return {
                "chapter": data,
                "bundle": 1,
                "trans": {
                    "filename": "",
                    "position": 0,
                    "scroll_y": 0
                }
            }

        if not isinstance(data, dict):
            return {}

        return data

    def save_progress(self, save_scroll=False):
        """
        progress.json 저장.

        save_scroll=False:
            EPUB 회차 진행도만 저장.
            기존 trans.scroll_y는 절대로 변경하지 않는다.

        save_scroll=True:
            사용자의 실제 스크롤 또는 이전/다음 페이지 이동 후
            self.saved_scroll_y를 trans.scroll_y에 저장한다.

        중요:
            일반적인 save_progress() 호출로는 기존 scroll_y를
            절대로 덮어쓰지 않는다.
        """

        if not self.current_filename:
            return

        target_path = self.get_progress_file_path()
        progress = self.load_progress()

        # ---------------------------------------------------------
        # 기존 데이터
        # ---------------------------------------------------------
        old_data = progress.get(
            self.current_filename,
            1
        )

        # ---------------------------------------------------------
        # 구버전 숫자 구조 변환
        # ---------------------------------------------------------
        if isinstance(old_data, int):

            epub_progress = {
                "chapter": old_data,
                "bundle": self.get_bundle_size(),
                "trans": {
                    "filename": "",
                    "position": 0,
                    "scroll_y": 0
                }
            }

        elif isinstance(old_data, dict):

            # 기존 dict 자체를 수정하되
            # trans 내부의 기존 scroll_y를 보존한다.
            epub_progress = old_data

        else:

            epub_progress = {}

        # ---------------------------------------------------------
        # EPUB 회차 진행도
        #
        # current_index가 -1이면 기존 chapter 유지
        # ---------------------------------------------------------
        if self.current_index >= 0:
            epub_progress["chapter"] = (
                self.current_index + 1
            )

        # ---------------------------------------------------------
        # EPUB 회차 묶음
        # ---------------------------------------------------------
        epub_progress["bundle"] = self.get_bundle_size()

        # =========================================================
        # trans 데이터 처리
        #
        # ★ 핵심
        #
        # save_scroll=False:
        #   trans.scroll_y를 절대로 건드리지 않는다.
        #
        # save_scroll=True:
        #   현재 저장용 scroll_y를 명시적으로 기록한다.
        # =========================================================

        if self.trans_file_path:

            trans_data = epub_progress.get(
                "trans",
                {}
            )

            if not isinstance(trans_data, dict):
                trans_data = {}

            # -----------------------------------------------------
            # 실제 _trans.txt가 존재하는 경우
            # -----------------------------------------------------
            if os.path.exists(self.trans_file_path):

                # filename은 실제 파일명과 동기화
                trans_data["filename"] = os.path.basename(
                    self.trans_file_path
                )

                # -------------------------------------------------
                # ★ scroll_y는 명시적으로 저장하라고 한 경우에만
                # 변경한다.
                # -------------------------------------------------
                if save_scroll:

                    try:
                        trans_data["scroll_y"] = int(
                            self.saved_scroll_y
                        )
                    except Exception:
                        trans_data["scroll_y"] = 0

                # -------------------------------------------------
                # save_scroll=False이면 기존 scroll_y가 있으면
                # 그대로 유지한다.
                #
                # 단, 아직 trans_initialized=False이고
                # scroll_y가 없는 상태라면 여기서 만들지 않는다.
                # 최초 생성은 paste_clipboard()에서 한다.
                # -------------------------------------------------

                epub_progress["trans"] = trans_data

            else:

                # 실제 trans 파일이 없으면
                # 기존 trans 정보는 그대로 유지한다.
                #
                # 여기서 새 trans를 만들지 않는다.
                pass

        # ---------------------------------------------------------
        # progress.json 저장
        # ---------------------------------------------------------
        progress[self.current_filename] = epub_progress

        try:

            os.makedirs(
                os.path.dirname(target_path),
                exist_ok=True
            )

            with open(
                target_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    progress,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

        except Exception as e:

            print("진행도 저장 실패:", e)

    def _ensure_current_epub_progress(self):
        """
        현재 EPUB를 불러온 직후 progress.json에
        현재 EPUB의 기본 진행 상태가 없으면 즉시 생성한다.

        저장 대상:
            - chapter
            - bundle

        trans 정보는 여기서 새로 생성하지 않는다.
        """

        if not self.current_filename:
            return

        target_path = self.get_progress_file_path()

        progress = self.load_progress()

        old_data = progress.get(
            self.current_filename
        )

        if isinstance(old_data, dict):
            return

        if isinstance(old_data, int):
            chapter = old_data
        else:
            if self.current_index >= 0:
                chapter = self.current_index + 1
            else:
                chapter = 1

        bundle = self.get_bundle_size()

        progress[self.current_filename] = {
            "chapter": chapter,
            "bundle": bundle
        }

        try:

            os.makedirs(
                os.path.dirname(target_path),
                exist_ok=True
            )

            with open(
                target_path,
                "w",
                encoding="utf-8"
            ) as f:

                json.dump(
                    progress,
                    f,
                    ensure_ascii=False,
                    indent=2
                )

            print(
                f"[PROGRESS] 현재 EPUB 진행도 즉시 생성: "
                f"{self.current_filename} "
                f"(chapter={chapter}, bundle={bundle})"
            )

        except Exception as e:

            print(
                f"[PROGRESS] 진행도 파일 생성 실패: {e}"
            )

    def restore_epub_progress(self, count):

        progress_data = self.get_current_progress()

        # -------------------------------------------------
        # 회차 진행도
        # -------------------------------------------------
        last = progress_data.get(
            "chapter",
            1
        )

        try:
            last = int(last)
        except Exception:
            last = 1

        # -------------------------------------------------
        # 회차 묶음
        # -------------------------------------------------
        bundle = progress_data.get(
            "bundle",
            1
        )

        try:
            bundle = max(
                1,
                int(bundle)
            )
        except Exception:
            bundle = 1

        if self.bundle_entry:
            self.bundle_entry.text = str(
                bundle
            )

        # -------------------------------------------------
        # EPUB 회차 위치 복원
        # -------------------------------------------------
        if count > 0:

            index = max(
                0,
                min(
                    last - 1,
                    count - 1
                )
            )

            self.select_list_item(index)

    def get_bundle_size(self):
        try:
            val = int(self.bundle_entry.text)
            return max(1, val)  # 최소값 1 보장
        except:
            return 1

    def get_chapter_text(self, index):
        # 💡 [수정] index를 int로 감싸 리스트 인덱스 접근 경고 해결
        target_idx = int(index)
        target_href = self.chapters[target_idx]["href"]

        with zipfile.ZipFile(self.epub_path) as z:
            html = z.read(target_href).decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html, "html.parser")

        return soup.get_text("\n")  # type: ignore

    def copy_to_clipboard(self, text):
        if droid:
            try:
                droid.setClipboard(text)
            except:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(text)
        else:
            from kivy.core.clipboard import Clipboard
            Clipboard.copy(text)

    def copy_selected_chapter(self):
        # 묶음 단위 가져오기
        bundle_size = self.get_bundle_size()

        # 1. 사용자가 직접 입력한 경우(chapter_entry)와 현재 인덱스를 우선순위로 처리
        try:
            if self.chapter_entry.text:
                self.current_index = int(self.chapter_entry.text) - 1
        except:
            pass  # 입력값이 없으면 현재 인덱스 유지

        # 범위 체크
        if self.current_index < 0 or self.current_index >= len(self.chapters):
            return

        # 2. 묶음 범위만큼 텍스트 병합
        end_idx = min(self.current_index + bundle_size, len(self.chapters))
        text_to_copy = ""
        for i in range(self.current_index, end_idx):
            text_to_copy += self.get_chapter_text(i) + "\n\n"

        # 3. 클립보드 복사
        self.copy_to_clipboard(text_to_copy)

        # 4. 💡 진행도 저장 및 업데이트 (기존 로직 유지)
        self.save_progress()
        self.progress_label.text = f"진행도: {self.current_index + 1}/{len(self.chapters)}"
        self.current_title.text = f"복사 완료: {self.chapters[self.current_index]['title']} 외 {end_idx - self.current_index - 1}건"

        # 리스트 선택 UI 업데이트
        self.select_list_item(self.current_index)

    def copy_prev(self):
        bundle_size = self.get_bundle_size()
        self.current_index = max(0, self.current_index - bundle_size)
        self._update_list_and_copy()

    def copy_next(self):
        bundle_size = self.get_bundle_size()
        self.current_index = min(self.current_index + bundle_size, len(self.chapters) - 1)
        self._update_list_and_copy()

    def _update_list_and_copy(self):
        self.select_list_item(self.current_index)
        self.copy_selected_chapter()

    # ──────────────────────────────────────────────
    # 1. get_epubtoclipb_db_path
    # ──────────────────────────────────────────────
    def get_epubtoclipb_db_path(self):
        if not self.current_filename:
            return None

        cache_dir = _get_db_dir(getattr(self, 'user_data_dir', None))
        if not cache_dir:
            return None

        base_name = os.path.splitext(self.current_filename)[0]
        return os.path.join(cache_dir, f"{base_name}_toc.json")

    # ──────────────────────────────────────────────
    # 2. get_progress_file_path
    # ──────────────────────────────────────────────
    def get_progress_file_path(self):
        cache_dir = _get_db_dir(getattr(self, 'user_data_dir', None))
        if not cache_dir:
            # 최후 폴백: BASE_DIR 기준 절대경로 (임시폴더 아님)
            return os.path.join(BASE_DIR, "progress.json")
        return os.path.join(cache_dir, "progress.json")

    # ──────────────────────────────────────────────
    # 3. get_memo_file_path
    # ──────────────────────────────────────────────
    def get_memo_file_path(self):
        cache_dir = _get_db_dir(getattr(self, 'user_data_dir', None))
        if not cache_dir:
            return os.path.join(BASE_DIR, "memo.txt")
        return os.path.join(cache_dir, "memo.txt")

    # ──────────────────────────────────────────────
    # 4. load_epubtoclipb_db
    # ──────────────────────────────────────────────
    def load_epubtoclipb_db(self):
        cache_path = self.get_epubtoclipb_db_path()
        if not cache_path or not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            if "chapters" not in cache_data:
                return None
            return cache_data
        except Exception as e:
            print(f"[캐시 오류] 목차 로드 중 실패: {e}")
            return None

    # ──────────────────────────────────────────────
    # 5. save_epubtoclipb_db
    # ──────────────────────────────────────────────
    def save_epubtoclipb_db(self):
        cache_path = self.get_epubtoclipb_db_path()
        if not cache_path or not self.chapters:
            return
        try:
            cache_data = {
                "chapters": self.chapters,
                "translated_titles": {str(k): v for k, v in self.translated_titles.items()}
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"[캐시 저장] 완료: {cache_path}")
        except Exception as e:
            print(f"[캐시 오류] 목차 파일 저장 실패: {e}")

    # ──────────────────────────────────────────────
    # 6. translate_chapter_list  (변경 없음)
    # ──────────────────────────────────────────────
    def translate_chapter_list(self):
        if self.translated_titles and self.is_translated:
            self.refresh_listbox(self.translated_titles)
            self.trans_btn.text = "원문 목차"
            return

        self.trans_btn.text = "번역 중..."
        self.trans_btn.disabled = True

        translator = GoogleTranslator(source='auto', target='ko')
        translation_targets = []
        for i, ch in enumerate(self.chapters):
            original_title = ch['title']
            if original_title and not original_title.isdigit() and not any(
                    ord('가') <= ord(char) <= ord('힣') for char in original_title
            ):
                translation_targets.append(f"{i}_###_{original_title}")

        translated_map = {i: ch['title'] for i, ch in enumerate(self.chapters)}
        chunk_size = 50

        if translation_targets:
            for chunk_idx in range(0, len(translation_targets), chunk_size):
                chunk = translation_targets[chunk_idx:chunk_idx + chunk_size]
                try:
                    combined_text = "\n".join(chunk)
                    translated_combined = translator.translate(combined_text)
                    translated_lines = translated_combined.split("\n")
                    for line in translated_lines:
                        if "_###_" in line:
                            try:
                                parts = line.split("_###_", 1)
                                idx = int(parts[0].strip())
                                val = parts[1].strip()
                                translated_map[idx] = val
                            except:
                                pass
                except:
                    pass

        self.translated_titles = translated_map
        self.save_epubtoclipb_db()
        self.refresh_listbox(self.translated_titles)
        self.trans_btn.text = "원문 목차"
        self.trans_btn.disabled = False
        self.is_translated = True

    # ──────────────────────────────────────────────
    # 7. load_epub  (변경 없음)
    # ──────────────────────────────────────────────
    def load_epub(self, path):

        self.translated_titles = {}
        self.is_translated = False
        self.trans_btn.text = "목차 번역"

        # ---------------------------------------------------------
        # 현재 EPUB 설정
        # ---------------------------------------------------------
        self.epub_path = path
        self.current_filename = Path(path).name
        self.file_label.text = self.current_filename

        # ---------------------------------------------------------
        # 이전 EPUB의 예약 저장 이벤트 제거
        # ---------------------------------------------------------
        if getattr(
            self,
            "_trans_progress_save_event",
            None
        ):

            try:
                self._trans_progress_save_event.cancel()
            except Exception:
                pass

            self._trans_progress_save_event = None

        # ---------------------------------------------------------
        # trans 파일 경로 설정
        # ---------------------------------------------------------
        self.trans_file_path = (
            self._get_trans_file_path()
        )

        # =========================================================
        # ★ 가장 먼저 현재 EPUB의 trans 상태를 판정
        #
        # 이 함수는 기존 scroll_y를 읽기만 한다.
        # =========================================================
        self._initialize_trans_state()

        print(
            f"[TRANS] initialized="
            f"{self.trans_initialized}, "
            f"saved_scroll_y="
            f"{self.saved_scroll_y}"
        )

        # ---------------------------------------------------------
        # trans.txt 화면 로딩
        #
        # _initialize_trans_state()에서 판정한 상태를
        # _load_trans_text()가 다시 확인한다.
        # ---------------------------------------------------------
        self._load_trans_text()

        # ---------------------------------------------------------
        # 목차 캐시 확인
        # ---------------------------------------------------------
        cached_toc = self.load_epubtoclipb_db()

        if cached_toc:

            print(
                "🎉 [초고속 로딩] "
                "로컬 JSON에서 복원합니다."
            )

            self.chapters = cached_toc["chapters"]

            raw_trans = cached_toc.get(
                "translated_titles",
                {}
            )

            self.translated_titles = {
                int(k): v
                for k, v in raw_trans.items()
            }

            count = len(self.chapters)

            self.info_label.text = (
                f"회차 수: {count}"
            )

            if self.translated_titles:

                self.refresh_listbox(
                    self.translated_titles
                )

                self.trans_btn.text = "원문 목차"
                self.is_translated = True

            else:

                self.refresh_listbox({
                    i: ch["title"]
                    for i, ch in enumerate(
                        self.chapters
                    )
                })

            self.restore_epub_progress(
                count
            )

            self._ensure_current_epub_progress()

            return

        # ---------------------------------------------------------
        # 최초 EPUB 목차 파싱
        # ---------------------------------------------------------
        print(
            "🐢 [최초 로딩] "
            "캐시 없음 — 전체 목차 파싱 시작"
        )

        parser = PureEpubParser(path)

        raw_chapters = (
            parser.get_chapters()
        )

        self.chapters = []

        for item in raw_chapters:

            title = item.get(
                "title",
                ""
            ).strip()

            if any(
                kw in title.lower()
                for kw in [
                    "cover",
                    "표지",
                    "title",
                    "제목",
                    "안내"
                ]
            ):

                print(
                    f"무효 회차 스킵: {title}"
                )

                continue

            self.chapters.append(
                item
            )

        self.refresh_listbox({
            i: ch["title"]
            for i, ch in enumerate(
                self.chapters
            )
        })

        count = len(
            self.chapters
        )

        self.info_label.text = (
            f"회차 수: {count}"
        )

        self.save_epubtoclipb_db()

        self.restore_epub_progress(
            count
        )

        self._ensure_current_epub_progress()

if __name__ == "__main__":
    EpubViewerApp().run()