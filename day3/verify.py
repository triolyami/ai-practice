from itertools import permutations

from puzzle import AGES, CITIES, GROUND_TRUTH, NAMES, SOLUTION


def resident(city_map: dict, city: str) -> str:
    return next(n for n in NAMES if city_map[n] == city)


def clues_ok(city_map: dict, age_map: dict) -> bool:
    if city_map["Вера"] != "Казань":
        return False
    if city_map["Анна"] in ("Сочи", "Москва"):
        return False
    sochi, perm = resident(city_map, "Сочи"), resident(city_map, "Пермь")
    if age_map[sochi] != max(AGES):
        return False
    if age_map[perm] != age_map[sochi] - 6:
        return False
    if age_map["Борис"] <= age_map["Григорий"]:
        return False
    if age_map["Вера"] != age_map["Анна"] - 3:
        return False
    return True


def solve() -> list:
    found = []
    for cities in permutations(CITIES):
        city_map = dict(zip(NAMES, cities))
        for ages in permutations(AGES):
            age_map = dict(zip(NAMES, ages))
            if clues_ok(city_map, age_map):
                found.append((city_map, age_map))
    return found


def fmt(city_map: dict, age_map: dict) -> str:
    return "; ".join(f"{n} — {city_map[n]}, {age_map[n]}" for n in NAMES)


def main() -> None:
    found = solve()
    print(f"Перебор {len(CITIES)}!×{len(AGES)}! комбинаций: найдено решений — {len(found)}")
    for city_map, age_map in found:
        print(" ", fmt(city_map, age_map))
    if len(found) != 1:
        raise SystemExit("ОШИБКА: решение не единственно")
    city_map, age_map = found[0]
    expected = {n: {"city": city_map[n], "age": age_map[n]} for n in NAMES}
    if expected != SOLUTION:
        raise SystemExit(f"ОШИБКА: найденное решение не совпало с SOLUTION: {expected}")
    print("Решение единственно и совпадает с SOLUTION")
    print("Эталон:", GROUND_TRUTH)


if __name__ == "__main__":
    main()
