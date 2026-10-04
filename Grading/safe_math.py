"""Small, bounded arithmetic language for untrusted exam answers."""
from __future__ import annotations
import ast
import math
import operator
import re

_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
              ast.Div: operator.truediv, ast.Pow: operator.pow}
_FUNCTIONS = {'sqrt': math.sqrt, 'abs': abs}


def arithmetic_value(expression: str) -> float:
    text = str(expression).strip().lower()
    if not text or len(text) > 512:
        raise ValueError('Expression is empty or too long')
    text = re.sub(r'^[xy]\s*=\s*', '', text)
    text = text.replace('×', '*').replace('÷', '/').replace('−', '-')
    text = text.replace('²', '**2').replace('³', '**3').replace('^', '**')
    text = text.replace('{', '(').replace('}', ')').replace('π', 'pi')
    text = re.sub(r'√\s*(\d+(?:\.\d+)?)', r'sqrt(\1)', text).replace('√(', 'sqrt(')
    text = re.sub(r'(\d+(?:\.\d+)?)\s*%', r'(\1/100)', text)
    tree = ast.parse(text, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 96:
        raise ValueError('Expression is too complex')

    def evaluate(node, depth=0):
        if depth > 24:
            raise ValueError('Expression is too deep')
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = float(node.value)
        elif isinstance(node, ast.Name) and node.id in {'pi', 'e'}:
            value = getattr(math, node.id)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand, depth+1) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
            left, right = evaluate(node.left, depth+1), evaluate(node.right, depth+1)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError('Exponent is too large')
            value = _OPERATORS[type(node.op)](left, right)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
              and node.func.id in _FUNCTIONS and len(node.args) == 1 and not node.keywords):
            value = _FUNCTIONS[node.func.id](evaluate(node.args[0], depth+1))
        else:
            raise ValueError('Unsupported arithmetic expression')
        if isinstance(value, complex) or not math.isfinite(value) or abs(value) > 1e100:
            raise ValueError('Result is outside the supported range')
        return float(value)
    return evaluate(tree.body)
