"""Explicit offline packaged-app verification, using temporary user storage."""
import sys, os, time, json, tempfile
from pathlib import Path


def run():
    started=time.monotonic()
    report=Path(sys.argv[sys.argv.index('--smoke-report')+1])
    with tempfile.TemporaryDirectory(prefix='pps-bundle-smoke-') as temp:
        root=Path(temp).resolve()
        os.environ.update(PAST_PAPER_FINDER_DATA_DIR=str(root/'data'),PAST_PAPER_FINDER_CACHE_DIR=str(root/'cache'))
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QSettings, QCoreApplication, QEvent
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat,QSettings.Scope.UserScope,str(root/'qt'))
        import requests
        def offline(*args,**kwargs):raise requests.ConnectionError('Offline package verification')
        requests.sessions.Session.request=offline
        from PySide6.QtWidgets import QApplication
        app=QApplication([])
        from Core.gui_main import PastPaperFinderGUI
        from UI.localization import get_locale_manager
        from Core.runtime_paths import resource_path, user_data_path
        from Utils.gui_utils import ConfigManager
        from UI.profile_controls import get_profile
        from UI.theme import get_theme_manager
        PastPaperFinderGUI._show_groq_startup_warning_if_needed=lambda self:None
        PastPaperFinderGUI._maybe_show_onboarding_dialog=lambda self:None
        window=PastPaperFinderGUI();window.resize(1440,900);window.show();app.processEvents()
        result=dict(frozen=bool(getattr(sys,'frozen',False)),machine=__import__('platform').machine(),
                    usable_window_seconds=round(time.monotonic()-started,3))
        get_profile().set_name('Package test')
        assert window._profile_header.menu_name.text()=='Package test'
        assert ConfigManager.get_value('profile.display_name')=='Package test'
        assert not window.settings_btn.isVisibleTo(window)
        assert Path(user_data_path()).is_relative_to(root)
        assert Path(resource_path('Data','igcse_components_master.json')).is_file()
        assert Path(resource_path('UI','assets','app_icons','PastPaperStudio.icns')).is_file()
        for theme in ('Coffee Shop','Matcha Latte','OLED Light','OLED Dark','Crimson Meridian'):
            get_theme_manager().apply_theme(app,theme);app.processEvents()
            assert not app.windowIcon().isNull()
        for language in ('en_US','en_GB','es','hi','fr'):
            get_locale_manager(app).set_language(language);app.processEvents()
        window._dashboard.show_results();app.processEvents()
        assert window._dashboard.stack.currentWidget() is window.results_scroll
        window._dashboard.show_home();app.processEvents()
        window._show_settings_window();app.processEvents();window._settings_window.hide()
        import fitz
        document=fitz.open();page=document.new_page();page.insert_text((72,72),'Packaged PDF worker test')
        path=root/'test.pdf';document.save(str(path));document.close()
        from Core import pdf_service
        document=pdf_service.open(str(path))
        assert 'Packaged PDF worker test' in document[0].get_text()
        pixmap=document[0].get_pixmap(matrix=pdf_service.Matrix(2,2))
        assert pixmap.width>1000
        document.close();pdf_service.shutdown_pdf_service()
        # Verify the backend and SDK are present, without fetching models or contacting AI.
        import paddle
        from paddleocr import PaddleOCR
        from groq import Groq
        result.update(pdf_worker=True,ocr_backend=paddle.__version__,ai_sdk=True,profile=True,
                      themes=True,languages=True,external_user_storage=True)
        window._dashboard.shutdown()
        window._graceful_exit_finalizing=True;window.close();window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        result['total_seconds']=round(time.monotonic()-started,3)
        report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(result,indent=2)+'\n')
        return 0
