import os
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

# 순수 Kivy 레이아웃 및 레이블/버튼 위젯 체제 전환
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.scrollview import ScrollView
from kivy.uix.popup import Popup

# --- [안드로이드 단독 앱 최적화: 순수 Kivy 전역 폰트 락인] ---
from kivy.core.text import LabelBase
from kivy.lang import Builder

font_path = "cjkfont.otf"
if not os.path.exists(font_path):
    font_path = os.path.join(os.path.dirname(__file__), "cjkfont.otf")

if os.path.exists(font_path):
    # Kivy 핵심 폰트 명칭을 우리 폰트로 리다이렉트
    LabelBase.register(name="Roboto", fn_regular=font_path, fn_bold=font_path)
    print(f"[INFO] 순수 Kivy 기본 글꼴 등록 성공: {font_path}")
else:
    print("[WARNING] cjkfont.otf 파일이 없습니다. 한글이 깨질 수 있습니다.")

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
        middle_frame = BoxLayout(orientation="vertical", size_hint_y=0.7)

        scroll_view = ScrollView(bar_width=10)
        self.list_container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=3)
        self.list_container.bind(minimum_height=self.list_container.setter('height'))
        scroll_view.add_widget(self.list_container)

        middle_frame.add_widget(scroll_view)
        main_layout.add_widget(middle_frame)

        # =========================================================================
        # ◼️ [하단 프레임 - 30%] 제어 및 연속 복사 버튼 영역
        # =========================================================================
        bottom_frame = BoxLayout(orientation="vertical", size_hint_y=0.2, spacing=8)

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
        blank_label = Label(text="", size_hint_x=0.6)

        bundle_row.add_widget(bundle_label)
        bundle_row.add_widget(self.bundle_entry)
        bundle_row.add_widget(blank_label)

        spacer_line = Label(size_hint_y=None, height=2)

        # [하단 3행 - 40%] 대형 다음 회차 복사 버튼
        next_row = BoxLayout(orientation="horizontal", size_hint_y=0.4)
        self.next_btn = Button(
            text="다음 회차 복사",
            font_size="19sp",
            bold=True,
            size_hint_x=0.75,
            pos_hint={"center_x": 0.5},
            background_color=(0.28, 0.28, 0.28, 1)
        )
        self.next_btn.bind(on_release=lambda x: self.copy_next())

        next_layout = BoxLayout(orientation="horizontal")
        next_layout.add_widget(Label(size_hint_x=0.125))
        next_layout.add_widget(self.next_btn)
        next_layout.add_widget(Label(size_hint_x=0.125))
        next_row.add_widget(next_layout)

        # 하단 구조 적재
        bottom_frame.add_widget(status_row)
        bottom_frame.add_widget(control_row)
        bottom_frame.add_widget(bundle_row)
        bottom_frame.add_widget(spacer_line)
        bottom_frame.add_widget(next_row)
        main_layout.add_widget(bottom_frame)

        return main_layout

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
            if self.current_filename and self.current_index != -1:
                self.save_progress()
        except Exception as e:
            print("종료 전 자동 저장 실패:", e)
        self.stop()

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

    def load_epub(self, path):
        # 💡 [안전장치] 새 파일을 로드하므로 이전 파일의 번역 상태를 완전히 비웁니다.
        self.translated_titles = {}
        self.is_translated = False
        self.trans_btn.text = "목차 번역"

        self.epub_path = path
        self.current_filename = Path(path).name
        self.file_label.text = self.current_filename

        # 💡 [고속화 단계] 로컬 캐시 조회
        cached_toc = self.load_epubtoclipb_db()

        # 💡 캐시가 존재한다면? 복사에 필요한 href가 다 들어있으므로 무거운 무한 루프 생략!
        if cached_toc:
            print("🎉 [초고속 로딩] 로컬 JSON에서 원문 구조 및 번역 목차를 즉시 복원합니다.")
            self.chapters = cached_toc["chapters"]

            # JSON 문자열 키를 정수형(int)으로 복원
            raw_trans = cached_toc.get("translated_titles", {})
            self.translated_titles = {int(k): v for k, v in raw_trans.items()}

            # UI 업데이트
            count = len(self.chapters)
            self.info_label.text = f"회차 수: {count}"

            if self.translated_titles:
                self.refresh_listbox(self.translated_titles)
                self.trans_btn.text = "원문 목차"
                self.is_translated = True
            else:
                self.refresh_listbox({i: ch['title'] for i, ch in enumerate(self.chapters)})

            # 진행도 로드 후 즉시 조기 종료(Return)
            progress = self.load_progress()
            last = progress.get(self.current_filename, 1)
            if count > 0:
                self.select_list_item(max(0, min(last - 1, count - 1)))
            return  # 💡 파싱 종료! 아래의 무거운 필터링 코드를 타지 않습니다.

        # ◼️ 캐시가 없을 때만 실행되는 최초 1회용 무거운 필터링 로직
        print("🐢 [최초 로딩] 캐시가 없어 전체 목차 필터링을 진행합니다.")
        parser = PureEpubParser(path)
        raw_chapters = parser.get_chapters()
        self.chapters = []

        for item in raw_chapters:
            title = item.get('title', '').strip()
            # 표지나 안내 등 무효한 키워드가 포함되면 스킵
            if any(kw in title.lower() for kw in ['cover', '표지', 'title', '제목', '안내']):
                print(f"무효 회차 스킵 처리: {title}")
                continue
            self.chapters.append(item)

        # UI 업데이트
        self.refresh_listbox({i: ch['title'] for i, ch in enumerate(self.chapters)})
        count = len(self.chapters)
        self.info_label.text = f"회차 수: {count}"

        # 💡 최초 파싱 성공했으므로 다음번을 위해 캐시 데이터 구워두기
        self.save_epubtoclipb_db()

        # 진행도 로드
        progress = self.load_progress()
        last = progress.get(self.current_filename, 1)
        if count > 0:
            self.select_list_item(max(0, min(last - 1, count - 1)))

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

    def translate_chapter_list(self):
        # 1. 이미 번역 작업이 완료되어 보고 있는 상태라면 중복 실행 방지
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
            if original_title and not original_title.isdigit() and not any(ord('가') <= ord(char) <= ord('힣') for char in original_title):
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

        # 번역 결과를 클래스 변수에 저장하여 재사용 준비
        self.translated_titles = translated_map

        # 최초 번역 완료 후 로컬에 파일로 저장
        self.save_epubtoclipb_db()

        # 💡 [싱크 맞춤] 리스트박스에 번역 목차를 뿌리고, 버튼은 "원문 목차"로 대기
        self.refresh_listbox(self.translated_titles)
        self.trans_btn.text = "원문 목차"
        self.trans_btn.disabled = False
        self.is_translated = True

    def update_status_label(self, index):
        # 💡 [수정] index를 int로 명시하여 안전하게 변환
        target_idx = int(index)

        # 현재 번역 상태에 따라 제목을 선택
        if self.is_translated and target_idx in self.translated_titles:
            display_title = self.translated_titles[target_idx]
        else:
            display_title = self.chapters[target_idx]['title']

        self.current_title.text = f"복사 완료: {display_title}"

    def get_progress_file_path(self):
        # 💡 기존의 안정적인 폴더 탐색 로직을 그대로 재활용하여 폴더 경로 확보
        cache_dir = None
        if platform == 'android' or 'ANDROID_ARGUMENT' in os.environ:
            public_dir = "/storage/emulated/0/Documents/epubtoclipb_db"
            try:
                os.makedirs(public_dir, exist_ok=True)
                cache_dir = public_dir
            except:
                try:
                    private_dir = os.path.join(self.user_data_dir, "epubtoclipb_db")
                    os.makedirs(private_dir, exist_ok=True)
                    cache_dir = private_dir
                except:
                    return "progress.json"  # 최종 실패 시 기본 파일명 분기
        else:
            try:
                script_dir = os.path.dirname(os.path.abspath(__file__))
                pc_dir = os.path.join(script_dir, "epubtoclipb_db")
                os.makedirs(pc_dir, exist_ok=True)
                cache_dir = pc_dir
            except:
                return "progress.json"

        if not cache_dir:
            return "progress.json"

        # 💡 해당 폴더 내부에 progress.json 이름으로 단일 파일 생성 지정
        return os.path.join(cache_dir, "progress.json")

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

    def save_progress(self):
        if not self.current_filename:
            return
        # 💡 동적 경로를 호출하여 저장
        target_path = self.get_progress_file_path()
        progress = self.load_progress()
        progress[self.current_filename] = self.current_index + 1
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(progress, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("진행도 저장 실패:", e)

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

    def get_epubtoclipb_db_path(self):
        if not self.current_filename:
            return None

        cache_dir = None

        # ◼️ 1. 안드로이드 환경일 때 (Pydroid3 포함)
        if platform == 'android' or 'ANDROID_ARGUMENT' in os.environ:
            # [1단계] 안드로이드 공용 폴더(내문서) 타겟팅
            public_dir = "/storage/emulated/0/Documents/epubtoclipb_db"
            try:
                # 사용자가 미리 만들어두었거나 앱에 파일 쓰기 권한이 있으면 성공
                os.makedirs(public_dir, exist_ok=True)
                cache_dir = public_dir
                print(f"[안드로이드 1단계 성공] 내문서 저장: {cache_dir}")
            except Exception as e:
                # [2단계] 권한 부족 등으로 실패하면 안전한 앱 내부 전용 폴더로 우회
                print(f"[안드로이드 1단계 실패] {e} -> 내부 폴더로 우회")
                try:
                    private_dir = os.path.join(self.user_data_dir, "epubtoclipb_db")
                    os.makedirs(private_dir, exist_ok=True)
                    cache_dir = private_dir
                    print(f"[안드로이드 2단계 성공] 앱 내부 저장: {cache_dir}")
                except Exception as e2:
                    print(f"[안드로이드 캐시 폴더 생성 최종 실패]: {e2}")
                    return None

        # ◼️ 2. PC 환경일 때 (거짓일 경우)
        else:
            try:
                # [PC 1단계] 현재 코드가 있는 스크립트 하위에 생성
                script_dir = os.path.dirname(os.path.abspath(__file__))
                pc_dir = os.path.join(script_dir, "epubtoclipb_db")
                os.makedirs(pc_dir, exist_ok=True)
                cache_dir = pc_dir
                print(f"[PC 환경 성공] 스크립트 하위 저장: {cache_dir}")
            except Exception as e:
                print(f"[PC 캐시 폴더 생성 실패]: {e}")
                return None

        if not cache_dir:
            return None

        # 최종 파일명과 결합하여 반환
        base_name = os.path.splitext(self.current_filename)[0]
        return os.path.join(cache_dir, f"{base_name}_toc.json")

    def save_epubtoclipb_db(self):
        cache_path = self.get_epubtoclipb_db_path()
        if not cache_path or not self.chapters:
            return
        try:
            # 💡 href와 title을 포함한 self.chapters 구조를 통째로 패키징
            cache_data = {
                "chapters": self.chapters,
                "translated_titles": {str(k): v for k, v in self.translated_titles.items()}
            }
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            print(f"[캐시 저장] 통합 목차 파일 저장 완료: {cache_path}")
        except Exception as e:
            print(f"[캐시 오류] 목차 파일 저장 실패: {e}")

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

if __name__ == "__main__":
    EpubViewerApp().run()