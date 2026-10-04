"""Scientific calculator widget and safe expression engine."""

from __future__ import annotations

import ast
import math
import random
import re
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from Utils.gui_utils import Colors


class CalculatorEngine:
    """Safe evaluator for scientific expressions (no eval())."""

    @staticmethod
    def evaluate(expr: str, angle_mode: str = "DEG", memory_state: Optional[Dict[str, float]] = None) -> float:
        text = (expr or "").strip()
        if not text:
            raise ValueError("Expression is empty")

        memory_value = float((memory_state or {}).get("memory", 0.0) or 0.0)
        prepared = CalculatorEngine._preprocess(text)
        node = ast.parse(prepared, mode="eval")
        return float(CalculatorEngine._eval_node(node.body, angle_mode=angle_mode, memory_value=memory_value))

    @staticmethod
    def _preprocess(expr: str) -> str:
        text = expr.strip()
        text = text.replace("×", "*").replace("÷", "/").replace("−", "-")
        text = text.replace("π", "pi")
        text = text.replace("^", "**")
        text = re.sub(r"\bANS\b", "ans", text, flags=re.IGNORECASE)

        # Percent postfix: "50%" -> "50/100"
        text = text.replace("%", "/100")

        # Factorial postfix for simple tokens/groups.
        pattern = re.compile(r"(\b\d+(?:\.\d+)?\b|\([^()]+\)|\b[a-zA-Z_][a-zA-Z0-9_]*\b)!")
        while True:
            updated = pattern.sub(r"fact(\1)", text)
            if updated == text:
                break
            text = updated

        return text

    @staticmethod
    def _eval_node(node: ast.AST, angle_mode: str, memory_value: float) -> float:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Invalid constant")

        if isinstance(node, ast.BinOp):
            left = CalculatorEngine._eval_node(node.left, angle_mode, memory_value)
            right = CalculatorEngine._eval_node(node.right, angle_mode, memory_value)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ValueError("Division by zero")
                return left / right
            if isinstance(node.op, ast.Pow):
                return left ** right
            if isinstance(node.op, ast.Mod):
                return left % right
            raise ValueError("Unsupported operator")

        if isinstance(node, ast.UnaryOp):
            value = CalculatorEngine._eval_node(node.operand, angle_mode, memory_value)
            if isinstance(node.op, ast.UAdd):
                return value
            if isinstance(node.op, ast.USub):
                return -value
            raise ValueError("Unsupported unary operator")

        if isinstance(node, ast.Name):
            key = node.id.lower()
            if key == "pi":
                return math.pi
            if key == "e":
                return math.e
            if key == "m":
                return float(memory_value)
            if key == "ans":
                return 0.0
            raise ValueError(f"Unknown symbol: {node.id}")

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("Invalid function call")
            func_name = node.func.id.lower()
            args = [CalculatorEngine._eval_node(arg, angle_mode, memory_value) for arg in node.args]
            return CalculatorEngine._call_function(func_name, args, angle_mode)

        raise ValueError("Unsupported expression")

    @staticmethod
    def _call_function(name: str, args: list[float], angle_mode: str) -> float:
        deg = str(angle_mode).upper() == "DEG"

        def _require(n: int) -> None:
            if len(args) != n:
                raise ValueError(f"{name} expects {n} argument(s)")

        def _to_radians(v: float) -> float:
            return math.radians(v) if deg else v

        def _from_radians(v: float) -> float:
            return math.degrees(v) if deg else v

        if name == "sin":
            _require(1)
            return math.sin(_to_radians(args[0]))
        if name == "cos":
            _require(1)
            return math.cos(_to_radians(args[0]))
        if name == "tan":
            _require(1)
            return math.tan(_to_radians(args[0]))
        if name == "asin":
            _require(1)
            return _from_radians(math.asin(args[0]))
        if name == "acos":
            _require(1)
            return _from_radians(math.acos(args[0]))
        if name == "atan":
            _require(1)
            return _from_radians(math.atan(args[0]))
        if name == "sinh":
            _require(1)
            return math.sinh(args[0])
        if name == "cosh":
            _require(1)
            return math.cosh(args[0])
        if name == "tanh":
            _require(1)
            return math.tanh(args[0])
        if name == "asinh":
            _require(1)
            return math.asinh(args[0])
        if name == "acosh":
            _require(1)
            return math.acosh(args[0])
        if name == "atanh":
            _require(1)
            return math.atanh(args[0])

        if name == "sqrt":
            _require(1)
            if args[0] < 0:
                raise ValueError("sqrt domain error")
            return math.sqrt(args[0])
        if name == "cbrt":
            _require(1)
            return math.copysign(abs(args[0]) ** (1.0 / 3.0), args[0])
        if name == "nroot":
            if len(args) != 2:
                raise ValueError("nroot expects 2 arguments: nroot(value, n)")
            value, n = args[0], args[1]
            if n == 0:
                raise ValueError("nroot with n=0")
            if value < 0 and int(round(n)) % 2 == 0:
                raise ValueError("even root of negative")
            return math.copysign(abs(value) ** (1.0 / n), value)

        if name == "ln":
            _require(1)
            if args[0] <= 0:
                raise ValueError("ln domain error")
            return math.log(args[0])
        if name == "log":
            if len(args) == 1:
                if args[0] <= 0:
                    raise ValueError("log domain error")
                return math.log10(args[0])
            if len(args) == 2:
                x, base = args
                if x <= 0 or base <= 0 or base == 1:
                    raise ValueError("log domain error")
                return math.log(x, base)
            raise ValueError("log expects 1 or 2 arguments")
        if name == "log2":
            _require(1)
            if args[0] <= 0:
                raise ValueError("log2 domain error")
            return math.log2(args[0])

        if name == "fact":
            _require(1)
            v = args[0]
            if abs(v - round(v)) > 1e-9 or v < 0:
                raise ValueError("factorial expects non-negative integer")
            return float(math.factorial(int(round(v))))

        if name == "abs":
            _require(1)
            return abs(args[0])
        if name == "exp":
            _require(1)
            return math.exp(args[0])

        raise ValueError(f"Unknown function: {name}")


class ScientificCalculatorWidget(QWidget):
    """Dock-friendly scientific calculator UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.memory_value = 0.0
        self.last_result = 0.0
        self.shift_mode = False
        self.shift_btn: Optional[QPushButton] = None
        self._trig_buttons: Dict[str, QPushButton] = {}
        self._hyperbolic_buttons: Dict[str, QPushButton] = {}
        self.setMinimumSize(980, 680)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setObjectName("scientificCalculator")
        self.setStyleSheet(
            "QWidget#scientificCalculator {"
            "  background-color: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #242a33, stop:1 #1b212b);"
            "}"
            "QFrame#displayFrame { background-color: #11161f; border-radius: 14px; border: 1px solid #2f3947; }"
            "QLineEdit#exprEdit { background-color: transparent; color: #f3f4f6; border: none; padding: 10px; font-size: 28px; }"
            "QLabel#resultLabel { color: #f8fafc; font-size: 62px; font-weight: 300; }"
            "QLabel#metaLabel { color: #d1d5db; font-size: 16px; }"
            "QComboBox#angleCombo { background-color: #2a3039; color: #f9fafb; border: 1px solid #4a5563; border-radius: 10px; "
            "padding: 6px 12px; padding-right: 28px; font-size: 18px; font-weight: 700; min-height: 34px; }"
            "QComboBox#angleCombo::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: none; }"
            "QComboBox#angleCombo QAbstractItemView { background-color: #222831; color: #f9fafb; "
            "border: 1px solid #4a5563; outline: 0px; }"
            "QComboBox#angleCombo QAbstractItemView::item { min-height: 28px; padding: 4px 10px; }"
            "QPushButton#calcKey { background-color: #323943; color: #f3f4f6; border: 1px solid #4b5563; border-radius: 22px; font-size: 22px; font-weight: 600; padding: 4px 6px; }"
            "QPushButton#calcKey:hover { background-color: #3b4350; }"
            "QPushButton#numKey { background-color: #4a5058; color: #f3f4f6; border: 1px solid #5a6472; border-radius: 22px; font-size: 34px; font-weight: 700; padding: 4px 6px; }"
            "QPushButton#numKey:hover { background-color: #585f69; }"
            "QPushButton#opKey { background-color: #ff9f0a; color: white; border: none; border-radius: 22px; font-size: 40px; font-weight: 700; padding: 4px 6px; }"
            "QPushButton#opKey:hover { background-color: #ffb340; }"
            "QPushButton#shiftKey { background-color: #5b626d; color: #f8fafc; border: none; border-radius: 22px; font-size: 20px; font-weight: 700; padding: 4px 6px; }"
            "QPushButton#shiftKey:hover { background-color: #6a7280; }"
            "QPushButton#shiftKey:checked { background-color: #f59e0b; color: #111827; }"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        display_frame = QFrame()
        display_frame.setObjectName("displayFrame")
        display_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        display_frame.setMaximumHeight(220)
        display_layout = QVBoxLayout(display_frame)
        display_layout.setContentsMargins(8, 8, 8, 8)
        self.expression_edit = QLineEdit()
        self.expression_edit.setObjectName("exprEdit")
        self.expression_edit.setPlaceholderText("Enter expression")
        self.expression_edit.setMinimumHeight(66)
        self.expression_edit.returnPressed.connect(self._evaluate_expression)
        self.result_label = QLabel("0")
        self.result_label.setObjectName("resultLabel")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        display_layout.addWidget(self.expression_edit)
        display_layout.addWidget(self.result_label)
        root.addWidget(display_frame)

        meta = QHBoxLayout()
        angle_label = QLabel("Angle")
        angle_label.setObjectName("metaLabel")
        meta.addWidget(angle_label)
        self.angle_combo = QComboBox()
        self.angle_combo.setObjectName("angleCombo")
        self.angle_combo.addItems(["DEG", "RAD"])
        self.angle_combo.setMinimumWidth(126)
        self.angle_combo.setMinimumHeight(42)
        self.angle_combo.view().setMinimumWidth(126)
        meta.addWidget(self.angle_combo)
        meta.addSpacing(8)
        self.memory_label = QLabel("M: 0")
        self.memory_label.setObjectName("metaLabel")
        meta.addWidget(self.memory_label)
        meta.addStretch(1)
        root.addLayout(meta)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)

        layout_rows = [
            ["(", ")", "MC", "M+", "M-", "MR", "DEL", "AC", "%", "÷"],
            ["SHIFT", "x²", "x³", "x^y", "y^x", "2^x", "7", "8", "9", "×"],
            ["1/x", "2√x", "3√x", "y√x", "log_y", "log2", "4", "5", "6", "−"],
            ["x!", "sin", "cos", "tan", "e", "EE", "1", "2", "3", "+"],
            ["Rand", "sinh", "cosh", "tanh", "π", "Rad", "+/-", "0", ".", "="],
        ]

        operator_tokens = {"÷", "×", "−", "+", "="}
        number_tokens = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "."}
        for r, row in enumerate(layout_rows):
            for c, token in enumerate(row):
                btn = QPushButton(token)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
                btn.setMinimumHeight(74)
                btn.setMinimumWidth(86)
                if token == "SHIFT":
                    btn.setObjectName("shiftKey")
                    btn.setCheckable(True)
                    btn.toggled.connect(self._toggle_shift_mode)
                    self.shift_btn = btn
                else:
                    if token in operator_tokens:
                        btn.setObjectName("opKey")
                    elif token in number_tokens:
                        btn.setObjectName("numKey")
                    else:
                        btn.setObjectName("calcKey")
                    btn.setProperty("token", token)
                    btn.clicked.connect(self._on_button_clicked)

                if token in {"sin", "cos", "tan"}:
                    self._trig_buttons[token] = btn
                if token in {"sinh", "cosh", "tanh"}:
                    self._hyperbolic_buttons[token] = btn

                grid.addWidget(btn, r, c)

        for c in range(10):
            grid.setColumnStretch(c, 1)

        root.addLayout(grid)
        root.setStretch(0, 0)
        root.setStretch(1, 0)
        root.setStretch(2, 1)
        self._update_shift_labels()
        self.apply_runtime_theme()

    @staticmethod
    def _mix_colors(start_hex: str, end_hex: str, ratio: float) -> str:
        start = QColor(start_hex)
        end = QColor(end_hex)
        t = max(0.0, min(1.0, float(ratio)))
        red = int(start.red() + (end.red() - start.red()) * t)
        green = int(start.green() + (end.green() - start.green()) * t)
        blue = int(start.blue() + (end.blue() - start.blue()) * t)
        return QColor(red, green, blue).name().upper()

    @staticmethod
    def _contrast_text_for_bg(bg_hex: str) -> str:
        return Colors.contrast_text_for_bg(bg_hex)

    def _build_theme_stylesheet(self) -> str:
        panel_top = self._mix_colors(Colors.BG_DARK, Colors.BG_CARD, 0.35)
        panel_bottom = self._mix_colors(Colors.BG_MEDIUM, Colors.BG_DARK, 0.25)
        display_bg = self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.40)
        display_border = self._mix_colors(Colors.BG_MEDIUM, Colors.PRIMARY, 0.30)
        key_border = self._mix_colors(Colors.BG_MEDIUM, Colors.BG_DARK, 0.35)
        calc_bg = self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.20)
        calc_hover = self._mix_colors(calc_bg, Colors.PRIMARY_HOVER, 0.30)
        num_bg = self._mix_colors(Colors.SECONDARY, Colors.BG_CARD, 0.40)
        num_hover = self._mix_colors(num_bg, Colors.SECONDARY_HOVER, 0.45)
        op_bg = self._mix_colors(Colors.PRIMARY, Colors.ACCENT_PINK, 0.20)
        op_hover = self._mix_colors(op_bg, Colors.PRIMARY_HOVER, 0.45)
        shift_bg = self._mix_colors(Colors.ACCENT_PURPLE, Colors.BG_CARD, 0.35)
        shift_hover = self._mix_colors(shift_bg, Colors.PRIMARY_HOVER, 0.35)
        shift_checked = self._mix_colors(Colors.WARNING, Colors.PRIMARY, 0.15)
        combo_bg = self._mix_colors(Colors.BG_LIGHT, Colors.BG_CARD, 0.30)
        combo_border = self._mix_colors(Colors.BG_MEDIUM, Colors.PRIMARY, 0.25)
        combo_popup_bg = self._mix_colors(Colors.BG_CARD, Colors.BG_DARK, 0.20)
        display_text = self._contrast_text_for_bg(display_bg)
        meta_text = self._mix_colors(display_text, Colors.TEXT_GRAY, 0.45)
        combo_text = self._contrast_text_for_bg(combo_bg)
        combo_popup_text = self._contrast_text_for_bg(combo_popup_bg)
        calc_text = self._contrast_text_for_bg(calc_bg)
        calc_hover_text = self._contrast_text_for_bg(calc_hover)
        num_text = self._contrast_text_for_bg(num_bg)
        num_hover_text = self._contrast_text_for_bg(num_hover)
        op_text = self._contrast_text_for_bg(op_bg)
        op_hover_text = self._contrast_text_for_bg(op_hover)
        shift_text = self._contrast_text_for_bg(shift_bg)
        shift_hover_text = self._contrast_text_for_bg(shift_hover)
        shift_checked_text = self._contrast_text_for_bg(shift_checked)
        return (
            "QWidget#scientificCalculator {"
            f"  background-color: qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {panel_top}, stop:1 {panel_bottom});"
            "}"
            f"QFrame#displayFrame {{ background-color: {display_bg}; border-radius: 14px; border: 1px solid {display_border}; }}"
            f"QLineEdit#exprEdit {{ background-color: transparent; color: {display_text}; border: none; padding: 10px; font-size: 28px; }}"
            f"QLabel#resultLabel {{ color: {display_text}; font-size: 62px; font-weight: 300; }}"
            f"QLabel#metaLabel {{ color: {meta_text}; font-size: 16px; }}"
            f"QComboBox#angleCombo {{ background-color: {combo_bg}; color: {combo_text}; border: 1px solid {combo_border}; border-radius: 10px; "
            "padding: 6px 12px; padding-right: 28px; font-size: 18px; font-weight: 700; min-height: 34px; }"
            "QComboBox#angleCombo::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border: none; }"
            f"QComboBox#angleCombo QAbstractItemView {{ background-color: {combo_popup_bg}; color: {combo_popup_text}; "
            f"border: 1px solid {combo_border}; outline: 0px; }}"
            "QComboBox#angleCombo QAbstractItemView::item { min-height: 28px; padding: 4px 10px; }"
            f"QPushButton#calcKey {{ background-color: {calc_bg}; color: {calc_text}; border: 1px solid {key_border}; border-radius: 22px; font-size: 22px; font-weight: 600; padding: 4px 6px; }}"
            f"QPushButton#calcKey:hover {{ background-color: {calc_hover}; color: {calc_hover_text}; }}"
            f"QPushButton#numKey {{ background-color: {num_bg}; color: {num_text}; border: 1px solid {key_border}; border-radius: 22px; font-size: 34px; font-weight: 700; padding: 4px 6px; }}"
            f"QPushButton#numKey:hover {{ background-color: {num_hover}; color: {num_hover_text}; }}"
            f"QPushButton#opKey {{ background-color: {op_bg}; color: {op_text}; border: 1px solid {key_border}; border-radius: 22px; font-size: 40px; font-weight: 700; padding: 4px 6px; }}"
            f"QPushButton#opKey:hover {{ background-color: {op_hover}; color: {op_hover_text}; }}"
            f"QPushButton#shiftKey {{ background-color: {shift_bg}; color: {shift_text}; border: 1px solid {key_border}; border-radius: 22px; font-size: 20px; font-weight: 700; padding: 4px 6px; }}"
            f"QPushButton#shiftKey:hover {{ background-color: {shift_hover}; color: {shift_hover_text}; }}"
            f"QPushButton#shiftKey:checked {{ background-color: {shift_checked}; color: {shift_checked_text}; }}"
        )

    def apply_runtime_theme(self) -> None:
        self.setStyleSheet(self._build_theme_stylesheet())

    def _on_button_clicked(self) -> None:
        sender = self.sender()
        if not isinstance(sender, QPushButton):
            return
        token = sender.property("token")
        if token is None:
            return
        self._on_button(str(token))

    def _toggle_shift_mode(self, enabled: bool) -> None:
        self.shift_mode = bool(enabled)
        self._update_shift_labels()

    def _update_shift_labels(self) -> None:
        trig_labels = (
            {"sin": "sin^-1", "cos": "cos^-1", "tan": "tan^-1"}
            if self.shift_mode
            else {"sin": "sin", "cos": "cos", "tan": "tan"}
        )
        for key, btn in self._trig_buttons.items():
            btn.setText(trig_labels.get(key, key))

        hyper_labels = (
            {"sinh": "sinh^-1", "cosh": "cosh^-1", "tanh": "tanh^-1"}
            if self.shift_mode
            else {"sinh": "sinh", "cosh": "cosh", "tanh": "tanh"}
        )
        for key, btn in self._hyperbolic_buttons.items():
            btn.setText(hyper_labels.get(key, key))

    def _append(self, text: str) -> None:
        self.expression_edit.insert(text)
        self.expression_edit.setFocus()

    def _set_result(self, value: float) -> None:
        self.last_result = float(value)
        disp = f"{value:.12g}"
        self.result_label.setText(disp)

    def _memory_operand(self) -> float:
        expr = self.expression_edit.text().strip()
        if expr:
            return CalculatorEngine.evaluate(expr, self.angle_combo.currentText(), {"memory": self.memory_value})
        return float(self.last_result)

    def _update_memory_label(self) -> None:
        self.memory_label.setText(f"M: {self.memory_value:.12g}")

    def _evaluate_expression(self) -> None:
        expr = self.expression_edit.text().strip()
        if not expr:
            return
        try:
            value = CalculatorEngine.evaluate(expr, self.angle_combo.currentText(), {"memory": self.memory_value})
            self._set_result(value)
        except Exception as exc:
            self.result_label.setText(f"Error: {exc}")

    def _on_button(self, token: str) -> None:
        if token in {"AC", "C"}:
            self.expression_edit.clear()
            self.result_label.setText("0")
            return
        if token == "DEL":
            text = self.expression_edit.text()
            self.expression_edit.setText(text[:-1])
            return
        if token == "=":
            self._evaluate_expression()
            return
        if token == "Rad":
            self.angle_combo.setCurrentText("RAD" if self.angle_combo.currentText() == "DEG" else "DEG")
            return
        if token == "+/-":
            text = self.expression_edit.text()
            if text.startswith("-"):
                self.expression_edit.setText(text[1:])
            elif text:
                self.expression_edit.setText(f"-{text}")
            else:
                self.expression_edit.setText("-")
            self.expression_edit.setFocus()
            return
        if token == "Rand":
            self._append(f"{random.random():.12g}")
            return
        if token == "MC":
            self.memory_value = 0.0
            self._update_memory_label()
            return
        if token == "MR":
            self._append(f"{self.memory_value:.12g}")
            return
        if token == "M+":
            try:
                self.memory_value += self._memory_operand()
                self._update_memory_label()
            except Exception as exc:
                self.result_label.setText(f"Error: {exc}")
            return
        if token == "M-":
            try:
                self.memory_value -= self._memory_operand()
                self._update_memory_label()
            except Exception as exc:
                self.result_label.setText(f"Error: {exc}")
            return

        token_map: Dict[str, str] = {
            "x^y": "^",
            "y^x": "^",
            "x²": "^2",
            "x³": "^3",
            "2^x": "2^(",
            "1/x": "1/(",
            "2√x": "sqrt(",
            "3√x": "cbrt(",
            "y√x": "nroot(",
            "log_y": "log(",
            "log2": "log2(",
            "x!": "!",
            "pi": "pi",
            "π": "pi",
            "e": "e",
            "EE": "e+",
            "ANS": f"{self.last_result:.12g}",
            ",": ",",
            "!": "!",
            "%": "%",
            "÷": "/",
            "×": "*",
            "−": "-",
        }

        if token in {"sin", "cos", "tan"}:
            if self.shift_mode:
                inverse_map = {"sin": "asin", "cos": "acos", "tan": "atan"}
                self._append(inverse_map[token] + "(")
            else:
                self._append(token + "(")
            return

        if token in {"sinh", "cosh", "tanh"}:
            if self.shift_mode:
                inverse_map = {"sinh": "asinh", "cosh": "acosh", "tanh": "atanh"}
                self._append(inverse_map[token] + "(")
            else:
                self._append(token + "(")
            return

        if token in {"asin", "acos", "atan", "ln", "log", "sqrt", "cbrt", "nroot", "exp", "abs"}:
            self._append(token + "(")
            return

        self._append(token_map.get(token, token))
