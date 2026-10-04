"""Keep main state intact while an independent exam owns interaction."""
import weakref
from PySide6.QtWidgets import QWidget


class ExamWorkspaceLifecycle:
    def __init__(self, exam, main):
        self.exam = weakref.ref(exam)
        self.main = weakref.ref(main) if isinstance(main, QWidget) else lambda: None
        self.active = False
        self.visible = False
        self.enabled = True
        self.panels = []

    def enter(self):
        main = self.main()
        if self.active or main is None:
            return
        self.active = True
        self.visible, self.enabled = main.isVisible(), main.isEnabled()
        for panel in main.findChildren(QWidget):
            if panel is not self.exam() and panel.isWindow() and panel.isVisible():
                owner = panel.parentWidget()
                belongs_to_exam = False
                while owner:
                    if owner is self.exam():
                        belongs_to_exam = True
                        break
                    owner = owner.parentWidget()
                if not belongs_to_exam:
                    self.panels.append(weakref.ref(panel))
                    panel.hide()
        main.hide()
        main.setEnabled(False)
        timer = getattr(main, '_results_theme_refresh_timer', None)
        if timer:
            timer.stop()

    def leave(self):
        if not self.active:
            return
        self.active = False
        main = self.main()
        if main is None:
            return
        try:
            main.setEnabled(self.enabled)
            if getattr(main, '_graceful_exit_in_progress', False) or getattr(main, '_graceful_exit_finalizing', False):
                return
            if self.visible:
                main.show()
                main.raise_()
                main.activateWindow()
            for reference in self.panels:
                panel = reference()
                if panel is not None:
                    panel.show()
            if getattr(main, '_results_theme_refresh_scheduled', False):
                main._schedule_results_theme_refresh()
            if getattr(main, '_dashboard', None):
                main.refresh_history()
        except RuntimeError:
            pass
        finally:
            self.panels.clear()
