# Campus RCA Evaluation Report

## Summary

| Mode | Accuracy | Keyword cov. | Hallucination | Faithfulness | Avg ms |
|---|---:|---:|---:|---:|---:|
| hybrid | 1.0 | 0.78 | 0.333 | 0.9 | 9213.4 |
| rule_only | 1.0 | 0.78 | 0.0 | 1.0 | 4464.5 |
| llm_only | 0.0 | 0.0 | 0.333 | 0.5 | 9339.8 |

## Per-scenario

- `hybrid` / `student_acl_deny_mgt` [OK] pred=`acl_deny`@core_sw1 truth=`acl_deny`@core_sw1
- `rule_only` / `student_acl_deny_mgt` [OK] pred=`acl_deny`@core_sw1 truth=`acl_deny`@core_sw1
- `llm_only` / `student_acl_deny_mgt` [MISS] pred=`unknown`@None truth=`acl_deny`@core_sw1
- `hybrid` / `guest_wlan_acl_deny` [OK] pred=`acl_deny`@core_sw1 truth=`acl_deny`@core_sw1
- `rule_only` / `guest_wlan_acl_deny` [OK] pred=`acl_deny`@core_sw1 truth=`acl_deny`@core_sw1
- `llm_only` / `guest_wlan_acl_deny` [MISS] pred=`unknown`@None truth=`acl_deny`@core_sw1
- `hybrid` / `missing_ospf_students` [OK] pred=`missing_route`@dsw_b_student truth=`missing_route`@dsw_b_student
- `rule_only` / `missing_ospf_students` [OK] pred=`missing_route`@dsw_b_student truth=`missing_route`@dsw_b_student
- `llm_only` / `missing_ospf_students` [MISS] pred=`unknown`@None truth=`missing_route`@dsw_b_student
- `hybrid` / `core1_uplink_shutdown` [OK] pred=`interface_down`@core_sw1 truth=`interface_down`@core_sw1
- `rule_only` / `core1_uplink_shutdown` [OK] pred=`interface_down`@core_sw1 truth=`interface_down`@core_sw1
- `llm_only` / `core1_uplink_shutdown` [MISS] pred=`unknown`@None truth=`interface_down`@core_sw1
- `hybrid` / `wrong_default_route_r1` [OK] pred=`wrong_static_route`@campus_r1 truth=`wrong_static_route`@campus_r1
- `rule_only` / `wrong_default_route_r1` [OK] pred=`wrong_static_route`@campus_r1 truth=`wrong_static_route`@campus_r1
- `llm_only` / `wrong_default_route_r1` [MISS] pred=`unknown`@None truth=`wrong_static_route`@campus_r1
- `hybrid` / `ospf_omit_academic` [OK] pred=`missing_route`@dsw_a_acad truth=`missing_route`@dsw_a_acad
- `rule_only` / `ospf_omit_academic` [OK] pred=`missing_route`@dsw_a_acad truth=`missing_route`@dsw_a_acad
- `llm_only` / `ospf_omit_academic` [MISS] pred=`unknown`@None truth=`missing_route`@dsw_a_acad
- `hybrid` / `dmz_to_lan_leak_attempt` [OK] pred=`acl_deny`@fw1 truth=`acl_deny`@fw1
- `rule_only` / `dmz_to_lan_leak_attempt` [OK] pred=`acl_deny`@fw1 truth=`acl_deny`@fw1
- `llm_only` / `dmz_to_lan_leak_attempt` [MISS] pred=`unknown`@None truth=`acl_deny`@fw1
- `hybrid` / `fw1_inside_shutdown` [OK] pred=`interface_down`@fw1 truth=`interface_down`@fw1
- `rule_only` / `fw1_inside_shutdown` [OK] pred=`interface_down`@fw1 truth=`interface_down`@fw1
- `llm_only` / `fw1_inside_shutdown` [MISS] pred=`unknown`@None truth=`interface_down`@fw1
- `hybrid` / `core2_student_uplink_down` [OK] pred=`interface_down`@core_sw2 truth=`interface_down`@core_sw2
- `rule_only` / `core2_student_uplink_down` [OK] pred=`interface_down`@core_sw2 truth=`interface_down`@core_sw2
- `llm_only` / `core2_student_uplink_down` [MISS] pred=`unknown`@None truth=`interface_down`@core_sw2
- `hybrid` / `missing_ospf_dns_services` [OK] pred=`missing_route`@dsw_d_dc truth=`missing_route`@dsw_d_dc
- `rule_only` / `missing_ospf_dns_services` [OK] pred=`missing_route`@dsw_d_dc truth=`missing_route`@dsw_d_dc
- `llm_only` / `missing_ospf_dns_services` [MISS] pred=`unknown`@None truth=`missing_route`@dsw_d_dc