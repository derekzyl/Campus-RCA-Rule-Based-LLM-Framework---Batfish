# Campus RCA Evaluation Report

## Summary

| Mode | Accuracy | Keyword cov. | Hallucination | Faithfulness | Avg ms |
|---|---:|---:|---:|---:|---:|
| rule_only | 1.0 | 0.693 | 0.0 | 1.0 | 0.6 |

## Per-scenario

- `rule_only` / `student_acl_deny_mgt` [OK] pred=`acl_deny`@core_sw1 truth=`acl_deny`@core_sw1
- `rule_only` / `guest_wlan_acl_deny` [OK] pred=`acl_deny`@core_sw1 truth=`acl_deny`@core_sw1
- `rule_only` / `missing_ospf_students` [OK] pred=`missing_route`@dsw_b_student truth=`missing_route`@dsw_b_student
- `rule_only` / `core1_uplink_shutdown` [OK] pred=`interface_down`@core_sw1 truth=`interface_down`@core_sw1
- `rule_only` / `wrong_default_route_r1` [OK] pred=`wrong_static_route`@campus_r1 truth=`wrong_static_route`@campus_r1
- `rule_only` / `ospf_omit_academic` [OK] pred=`missing_route`@dsw_a_acad truth=`missing_route`@dsw_a_acad
- `rule_only` / `dmz_to_lan_leak_attempt` [OK] pred=`acl_deny`@fw1 truth=`acl_deny`@fw1
- `rule_only` / `fw1_inside_shutdown` [OK] pred=`interface_down`@fw1 truth=`interface_down`@fw1
- `rule_only` / `core2_student_uplink_down` [OK] pred=`interface_down`@core_sw2 truth=`interface_down`@core_sw2
- `rule_only` / `missing_ospf_dns_services` [OK] pred=`missing_route`@dsw_d_dc truth=`missing_route`@dsw_d_dc