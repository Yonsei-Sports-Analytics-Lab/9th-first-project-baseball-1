# llm_client 검증용 투수 조합 50개

`validate_response()` 가 실제로 얼마나 자주 경고를 내는지 측정하기 위한 입력 목록입니다.

## 어떻게 고른 조합인가

- **유사 투수는 `find_nearest_pitcher(..., rank=1)` 의 실제 결과**입니다. 임의 조합이 아니라 서비스가 실제로 만들어내는 쌍이라, 여기서 나온 경고율이 곧 운영 중 경고율입니다.
- 입력·유사 투수 **양쪽 모두** `pitch_arsenal.pkl` 에 주 패스트볼과 변화구가 있는 시즌만 골랐습니다. 한쪽이라도 없으면 `llm_client` 가 `ValueError` 로 죽습니다.
- 전체 유효 조합 2,312개 중에서 **연도 10개씩 × 5년**, 클러스터는 연도당 한 곳에 3개를 넘지 않게, 입력 투수는 **50명 전원 서로 다르게** 뽑았습니다.
- 유사 투수의 변화구 개수가 많은 쪽을 우선했습니다 (`transfer_targets` 가 많을수록 `target_shape` 산술 검증이 많이 걸리므로).

| 항목 | 분포 |
|---|---|
| 연도 | 2021~2025 각 10개 |
| 투수 손 | 우완 37 · 좌완 13 |
| 클러스터 | C1 10개, C2 11개, C3 2개, C4 12개, C5 15개 |
| 유사 투수 변화구 수 | 중앙값 6개 |

> ⚠️ 이 조합은 **현재(시범경기 포함) 전처리 산출물** 기준입니다. `extract_fastball.py` 수정 후 파이프라인을 다시 돌리면 클러스터가 재배정되어 유사 투수 매칭이 달라질 수 있으니, 재생성 후에는 이 목록도 다시 뽑아야 합니다.

## 명령어 50개

```bash
#  1. Chad Kuhl 2021 (R) → Yu Darvish 2024
python -m src.utils.llm_client 641771 2021 506433 2024
#  2. Riley Smith 2021 (R) → Chris Bassitt 2023
python -m src.utils.llm_client 642092 2021 605135 2023
#  3. Bryse Wilson 2021 (R) → Yu Darvish 2022
python -m src.utils.llm_client 669060 2021 506433 2022
#  4. Bryan Abreu 2021 (R) → Yu Darvish 2021
python -m src.utils.llm_client 650556 2021 506433 2021
#  5. Josh Tomlin 2021 (R) → Aaron Civale 2022
python -m src.utils.llm_client 458708 2021 650644 2022
#  6. Tony Santillan 2021 (R) → Michael Lorenzen 2025
python -m src.utils.llm_client 663574 2021 547179 2025
#  7. Antonio Senzatela 2021 (R) → Max Fried 2025
python -m src.utils.llm_client 622608 2021 608331 2025
#  8. Chi Chi González 2021 (R) → Randy Vásquez 2025
python -m src.utils.llm_client 592346 2021 681190 2025
#  9. Cionel Pérez 2021 (L) → Luke Weaver 2023
python -m src.utils.llm_client 672335 2021 596133 2023
# 10. Trevor Bauer 2021 (R) → Bryce Miller 2024
python -m src.utils.llm_client 545333 2021 682243 2024
# 11. Hirokazu Sawamura 2022 (R) → Yu Darvish 2021
python -m src.utils.llm_client 617228 2022 506433 2021
# 12. Patrick Corbin 2022 (L) → Kyle Gibson 2022
python -m src.utils.llm_client 571578 2022 502043 2022
# 13. Jacob deGrom 2022 (R) → Shohei Ohtani 2025
python -m src.utils.llm_client 594798 2022 660271 2025
# 14. Andrés Muñoz 2022 (R) → Shohei Ohtani 2025
python -m src.utils.llm_client 662253 2022 660271 2025
# 15. Sonny Gray 2022 (R) → Chris Bassitt 2021
python -m src.utils.llm_client 543243 2022 605135 2021
# 16. Justin Steele 2022 (L) → Max Fried 2025
python -m src.utils.llm_client 657006 2022 608331 2025
# 17. Ryan Tepera 2022 (R) → Mitch Keller 2024
python -m src.utils.llm_client 572193 2022 656605 2024
# 18. Craig Stammen 2022 (R) → Dane Dunning 2023
python -m src.utils.llm_client 489334 2022 641540 2023
# 19. Andre Pallante 2022 (R) → Max Fried 2025
python -m src.utils.llm_client 669467 2022 608331 2025
# 20. Evan Phillips 2022 (R) → Corbin Burnes 2021
python -m src.utils.llm_client 623465 2022 669203 2021
# 21. Domingo Germán 2023 (R) → Seth Lugo 2024
python -m src.utils.llm_client 593334 2023 607625 2024
# 22. Colin Rea 2023 (R) → Yu Darvish 2023
python -m src.utils.llm_client 607067 2023 506433 2023
# 23. Génesis Cabrera 2023 (L) → Yu Darvish 2021
python -m src.utils.llm_client 650893 2023 506433 2021
# 24. Dakota Hudson 2023 (R) → Kyle Gibson 2021
python -m src.utils.llm_client 641712 2023 502043 2021
# 25. Andrew Chafin 2023 (L) → Kyle Gibson 2021
python -m src.utils.llm_client 605177 2023 502043 2021
# 26. Shintaro Fujinami 2023 (R) → Shohei Ohtani 2023
python -m src.utils.llm_client 660261 2023 660271 2023
# 27. Sam Hentges 2023 (L) → Shohei Ohtani 2022
python -m src.utils.llm_client 656529 2023 660271 2022
# 28. Griffin Jax 2023 (R) → Walker Buehler 2021
python -m src.utils.llm_client 643377 2023 621111 2021
# 29. Connor Phillips 2023 (R) → Walker Buehler 2021
python -m src.utils.llm_client 683175 2023 621111 2021
# 30. Clarke Schmidt 2023 (R) → Spencer Turnbull 2024
python -m src.utils.llm_client 657376 2023 605513 2024
# 31. Slade Cecconi 2024 (R) → Yu Darvish 2024
python -m src.utils.llm_client 677944 2024 506433 2024
# 32. Garrett Crochet 2024 (L) → Shohei Ohtani 2022
python -m src.utils.llm_client 676979 2024 660271 2022
# 33. Lucas Erceg 2024 (R) → Shohei Ohtani 2022
python -m src.utils.llm_client 668674 2024 660271 2022
# 34. Corbin Burnes 2024 (R) → Max Fried 2024
python -m src.utils.llm_client 669203 2024 608331 2024
# 35. Scott Alexander 2024 (L) → Chris Bassitt 2022
python -m src.utils.llm_client 518397 2024 605135 2022
# 36. Yariel Rodríguez 2024 (R) → Max Fried 2025
python -m src.utils.llm_client 684320 2024 608331 2025
# 37. Jake Woodford 2024 (R) → Yu Darvish 2025
python -m src.utils.llm_client 663765 2024 506433 2025
# 38. Merrill Kelly 2024 (R) → Spencer Turnbull 2024
python -m src.utils.llm_client 518876 2024 605513 2024
# 39. Sean Manaea 2024 (L) → Adam Ottavino 2024
python -m src.utils.llm_client 640455 2024 493603 2024
# 40. Yuki Matsui 2024 (L) → Nick Martinez 2024
python -m src.utils.llm_client 673513 2024 607259 2024
# 41. Shane Smith 2025 (R) → Shohei Ohtani 2023
python -m src.utils.llm_client 681343 2025 660271 2023
# 42. Luke Weaver 2025 (R) → Bryce Miller 2024
python -m src.utils.llm_client 596133 2025 682243 2024
# 43. Taylor Rogers 2025 (L) → Michael Lorenzen 2022
python -m src.utils.llm_client 573124 2025 547179 2022
# 44. Cade Smith 2025 (R) → Shohei Ohtani 2025
python -m src.utils.llm_client 671922 2025 660271 2025
# 45. Paul Skenes 2025 (R) → Shohei Ohtani 2025
python -m src.utils.llm_client 694973 2025 660271 2025
# 46. Bryce Miller 2025 (R) → Pedro Avila 2024
python -m src.utils.llm_client 682243 2025 658648 2024
# 47. Tyler Anderson 2025 (L) → Zack Greinke 2021
python -m src.utils.llm_client 542881 2025 425844 2021
# 48. Graham Ashcraft 2025 (R) → Corbin Burnes 2021
python -m src.utils.llm_client 668933 2025 669203 2021
# 49. Tim Mayza 2025 (L) → Kyle Gibson 2023
python -m src.utils.llm_client 641835 2025 502043 2023
# 50. Jonathan Cannon 2025 (R) → Zach Eflin 2024
python -m src.utils.llm_client 686563 2025 621107 2024
```

## 측정 방법

각 실행 결과 JSON의 `validation_warnings` 가 **빈 배열이면 통과**입니다. 50건 중 통과 건수를 세면 발표에 쓸 한 줄이 나옵니다.

경고가 나온 건은 어떤 유형인지 분류해 두세요 — `입력 데이터에 없는 구종`(환각), `target_shape.* ≠ 계산값`(산술), `수치를 인용하지 않은 근거`(근거 부실) 중 어느 쪽이 많은지가 그 자체로 결과입니다.

> API 호출 50회가 발생합니다. 무료 티어 분당 한도에 걸리면 `call_llm_with_fallback` 이 대체 모델로 넘어가므로, 모델별로 경고율이 섞이지 않게 `.env` 의 `LLM_MODEL` 을 고정해 두는 편이 깔끔합니다.
