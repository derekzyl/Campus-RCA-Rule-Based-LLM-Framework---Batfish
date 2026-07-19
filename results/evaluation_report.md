# Campus RCA Evaluation Report

## Summary

| Mode | Accuracy | Keyword cov. | Hallucination | Faithfulness | Avg ms |
|---|---:|---:|---:|---:|---:|
| rule_only | 1.0 | 0.813 | 0.0 | 1.0 | 0.3 |
| llm_only | 0.8 | 0.38 | 0.0 | 1.0 | 0.5 |
| hybrid | 1.0 | 0.573 | 0.0 | 1.0 | 0.4 |

## Per-scenario

- `rule_only` / `acl_deny_http` [OK] pred=`acl_deny`@dist2 truth=`acl_deny`@dist2
- `llm_only` / `acl_deny_http` [OK] pred=`acl_deny`@dist2 truth=`acl_deny`@dist2
- `hybrid` / `acl_deny_http` [OK] pred=`acl_deny`@dist2 truth=`acl_deny`@dist2
- `rule_only` / `missing_ospf_network` [OK] pred=`missing_route`@dist1 truth=`missing_route`@dist1
- `llm_only` / `missing_ospf_network` [OK] pred=`missing_route`@dist1 truth=`missing_route`@dist1
- `hybrid` / `missing_ospf_network` [OK] pred=`missing_route`@dist1 truth=`missing_route`@dist1
- `rule_only` / `interface_shutdown` [OK] pred=`interface_down`@core1 truth=`interface_down`@core1
- `llm_only` / `interface_shutdown` [OK] pred=`interface_down`@core1 truth=`interface_down`@core1
- `hybrid` / `interface_shutdown` [OK] pred=`interface_down`@core1 truth=`interface_down`@core1
- `rule_only` / `wrong_static_route` [OK] pred=`wrong_static_route`@core1 truth=`wrong_static_route`@core1
- `llm_only` / `wrong_static_route` [OK] pred=`wrong_static_route`@core1 truth=`wrong_static_route`@core1
- `hybrid` / `wrong_static_route` [OK] pred=`wrong_static_route`@core1 truth=`wrong_static_route`@core1
- `rule_only` / `ospf_passive_misconfig` [OK] pred=`missing_route`@dist2 truth=`missing_route`@dist2
- `llm_only` / `ospf_passive_misconfig` [MISS] pred=`acl_deny`@dist2 truth=`missing_route`@dist2
- `hybrid` / `ospf_passive_misconfig` [OK] pred=`missing_route`@dist2 truth=`missing_route`@dist2