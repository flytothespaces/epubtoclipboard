# epubtoclipboard
Epub 파일을 읽어서 목차에 해당하는 txt를 선택적으로 클립보드로 보내는 도구

# 📚 EPUB to Clipboard Viewer (Multi-Platform)

EPUB 전자책 파일의 목차 구조를 파싱하여 회차별 본문 텍스트를 손쉽게 클립보드에 연속 복사할 수 있는 유틸리티 프로그램입니다. PC 환경을 위한 **Tkinter 버전**과 안드로이드(모바일) 환경을 위한 **Kivy 버전**을 모두 제공합니다.

---

## ✨ 핵심 기능

- **고속화 캐싱 엔진 (SPHP 기반):** 최초 1회 로딩 이후부터는 로컬 JSON 데이터 구조(`_toc.json`)를 즉시 복원하여 무거운 파싱 과정 없이 초고속으로 목차를 띄웁니다.
- **스마트 목차 번역 (Google Translator API):** 원문 목차를 50화 단위 청크(Chunk)로 결합하여 딜레이와 비용을 최소화한 일괄 번역 기능을 제공합니다.
- **지능형 UI 토글:** 번역이 완료되면 `번역 목차` ↔ `원문 목차`가 동적으로 전환되며, 캐시가 있는 경우 중복 구글 API 요청 없이 로컬 메모리에서 즉시 스위칭됩니다.
- **다중 회차 묶음 복사:** 사용자가 지정한 세트 단위(예: 1권, 5화 묶음 등)로 본문 텍스트를 한 번에 병합하여 클립보드에 복사합니다.
- **진행도 통합 관리:** 스마트폰 내부 공용 경로(`Documents/epubtoclipb/`)에 단 하나의 `progress.json`을 생성하여 여러 EPUB 파일의 읽기 진도를 유기적으로 관리합니다.

---

## 🖥️ 1. PC 버전 실행 방법 (Tkinter)

### 📦 필수 요구사항
```bash
pip install beautifulsoup4 deep_translator

```

### 🚀 실행

`pc_tkinter` 폴더 진입 후 실행:

```bash
python EpubToClipboard_KV_TE.py

```

---

## 📲 2. 모바일 버전 실행 방법 (Android / Pydroid 3)

안드로이드 모바일 환경에서는 환경 오버헤드를 줄이기 위해 **터미널 설치**와 앱 자체 **Quick Install**을 분리하여 환경을 구축하는 것을 강력히 권장합니다.

### 🛠️ 단계별 설치 가이드

1. **Pydroid 3 앱 설치:** 구글 플레이 스토어에서 [Pydroid 3](https://play.google.com/store/apps/details?id=ru.iiec.pydroid3)를 다운로드합니다.
2. **Pip 엔진 업그레이드:** - 앱 내 왼쪽 상단 **메뉴(☰) ➡️ Terminal** 진입
* 다음 명령어 실행: `pip install --upgrade pip`


3. **핵심 GUI 라이브러리 설치 (App 전용 리포지토리):**
* 앱 내 왼쪽 상단 **메뉴(☰) ➡️ Pip ➡️ QUICK INSTALL** 탭 진입
* 목록에서 **`Kivy`** 및 `beautifulsoup4`를 찾아 각각 **INSTALL** 터치


4. **번역 엔진 설치 (터미널 복귀):**
* 앱 내 왼쪽 상단 **메뉴(☰) ➡️ Terminal** 재진입
* 다음 명령어 실행: `pip install deep_translator`



### 🚀 실행

* `cjkfont.otf` 파일을 소스코드와 동일한 경로에 배치한 후, `EpubToClipboard_KV_TE.py`를 열고 우하단의 **실행(▶️) 버튼**을 누릅니다.

---

## 📝 라이센스

이 프로젝트는 [MIT License](https://www.google.com/search?q=LICENSE)에 따라 자유롭게 수정 및 배포가 가능합니다.

```
