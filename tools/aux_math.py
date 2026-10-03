"""Float comparison helpers. Use these instead of ==, <, >= on floats."""
EPS = 1e-6


def eq(a, b):
    return abs(a - b) <= EPS


def ge(a, b):
    return a > b or eq(a, b)


def lt(a, b):
    return not ge(a, b)
