#!/usr/bin/env python3
"""Потужність двобічного точного критерію Фішера — симуляцією, не формулою.

Навіщо не формула Коена: арксинусне наближення асимптотичне й
антиконсервативне на малих частках. На 16 % проти 4 % воно дає n=44 для 80 %
потужності, а фактична потужність критерію Фішера на n=45 — 34 %.
Причина: критерій Фішера дискретний і консервативний, і на малих очікуваних
частотах різниця з асимптотикою велика.

Симуляція рахує потужність САМЕ того критерію, яким робиться замір.

    python3 tools/power_fisher.py --p1 0.16 --p2 0.04
    python3 tools/power_fisher.py --p1 0.16 --p2 0.04 --alpha 0.05 --reps 8000
"""
import argparse
import random
from math import comb


def fisher_two_sided(a, b, c, d):
    """p-value точного критерію Фішера для таблиці [[a,b],[c,d]].

    Двобічний варіант за методом сумування ймовірностей: додаємо всі таблиці
    з тими самими маргіналами, чия ймовірність не перевищує спостережену.
    """
    n = a + b + c + d
    row1, row2, col1 = a + b, c + d, a + c

    def prob(x):
        return comb(row1, x) * comb(row2, col1 - x) / comb(n, col1)

    p_obs = prob(a)
    lo, hi = max(0, col1 - row2), min(row1, col1)
    return sum(prob(x) for x in range(lo, hi + 1) if prob(x) <= p_obs + 1e-12)


def power(n, p1, p2, alpha, reps, rng):
    """Частка симуляцій, де критерій відхиляє нульову гіпотезу."""
    hits = 0
    for _ in range(reps):
        a = sum(rng.random() < p1 for _ in range(n))   # група 1: успіхів
        c = sum(rng.random() < p2 for _ in range(n))   # група 2: успіхів
        if fisher_two_sided(a, n - a, c, n - c) < alpha:
            hits += 1
    return hits / reps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--p1', type=float, required=True)
    ap.add_argument('--p2', type=float, required=True)
    ap.add_argument('--alpha', type=float, default=0.05)
    ap.add_argument('--reps', type=int, default=4000)
    ap.add_argument('--seed', type=int, default=7)
    ap.add_argument('--target', type=float, default=0.80)
    a = ap.parse_args()
    rng = random.Random(a.seed)

    print(f'частки {a.p1:.0%} проти {a.p2:.0%}, alpha={a.alpha}, '
          f'двобічний, {a.reps} повторів на точку')
    need = None
    for n in (25, 45, 60, 75, 90, 110, 130, 150):
        pw = power(n, a.p1, a.p2, a.alpha, a.reps, rng)
        flag = ''
        if need is None and pw >= a.target:
            need, flag = n, '   ← мінімум для цілі'
        print(f'  n={n:4} на групу → потужність {pw:5.1%}{flag}')
    if need:
        print(f'\nробоче число: {need} на групу, {2*need} карток усього')
    else:
        print('\nжодне з перевірених n не дає цільової потужності')


if __name__ == '__main__':
    main()
