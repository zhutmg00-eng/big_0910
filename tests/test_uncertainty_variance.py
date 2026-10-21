"""守卫：一阶方差分解必须对上解析值。

解析式（单车型、满载率不触发偏置、EF 与里程独立）：
  E = k·d·EF,  k = count/1000
  V_EF = k²·d0²·Var[EF]
  V_d  = k²·E[EF]²·Var[d]
  占比 = 各自 / (V_EF + V_d)

这批断言最初会是失败的——它锁定的正是「一阶贡献算错却被当成结论引用」
这个缺陷。修好引擎后此处应为绿。
"""

from src.engine.uncertainty import VehicleGroupData, ef_range, monte_carlo_emission


def _analytic(vt, count=10, d0=80000.0, cv=0.05):
    dist = ef_range(vt)
    a, m, b = dist["low"], dist["mode"], dist["high"]
    var_ef = (a * a + m * m + b * b - a * m - a * b - m * b) / 18.0
    mean_ef = (a + m + b) / 3.0
    k = count / 1000.0
    v_ef = k * k * d0 * d0 * var_ef
    v_d = k * k * mean_ef * mean_ef * (cv * d0) ** 2
    total = v_ef + v_d
    return v_ef / total, v_d / total, total


CASES = ("重型柴油货车", "中型柴油货车", "轻型柴油货车", "LNG重型货车")


def test_total_variance_matches_analytic():
    for vt in CASES:
        p_ef, p_d, tot = _analytic(vt)
        r = monte_carlo_emission([VehicleGroupData(vt, 10, 80000, 0.95)],
                                 n_samples=20000, data_quality="台账")
        assert abs(r.total_variance_t2 - tot) / tot < 0.05, (
            f"{vt} 总方差 {r.total_variance_t2} 偏离解析值 {tot:.1f} 超过 5%"
        )


def test_first_order_contributions_match_analytic():
    for vt in CASES:
        p_ef, p_d, _tot = _analytic(vt)
        r = monte_carlo_emission([VehicleGroupData(vt, 10, 80000, 0.95)],
                                 n_samples=20000, data_quality="台账")
        got_ef = r.variance_contributions.get(f"排放因子·{vt}")
        got_d = r.variance_contributions.get(f"年均里程·{vt}")
        assert got_ef is not None and got_d is not None, f"{vt} 缺少一阶贡献项"
        assert abs(got_ef - p_ef) < 0.06, f"{vt} EF 一阶贡献 {got_ef:.3f} 与解析 {p_ef:.3f} 差超过 0.06"
        assert abs(got_d - p_d) < 0.06, f"{vt} 里程一阶贡献 {got_d:.3f} 与解析 {p_d:.3f} 差超过 0.06"
