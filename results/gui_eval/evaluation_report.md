# Campus RCA Evaluation Report

## Summary

| Mode | Accuracy | Keyword cov. | Hallucination | Faithfulness | Avg ms |
|---|---:|---:|---:|---:|---:|
| hybrid | 0.8 | 0.613 | 0.333 | 0.6 | 158519.2 |
| rule_only | 0.8 | 0.613 | 0.0 | 1.0 | 2166.4 |
| llm_only | 0.2 | 0.26 | 0.0 | 0.9 | 133701.4 |

## Per-scenario

- `hybrid` / `acl_deny_http` [OK] pred=`acl_deny`@dist2 truth=`acl_deny`@dist2
- `rule_only` / `acl_deny_http` [OK] pred=`acl_deny`@dist2 truth=`acl_deny`@dist2
- `llm_only` / `acl_deny_http` [OK] pred=`acl_deny`@dist2 truth=`acl_deny`@dist2
- `hybrid` / `missing_ospf_network` [OK] pred=`missing_route`@dist1 truth=`missing_route`@dist1
- `rule_only` / `missing_ospf_network` [OK] pred=`missing_route`@dist1 truth=`missing_route`@dist1
- `llm_only` / `missing_ospf_network` [MISS] pred=`acl_deny`@dist1 truth=`missing_route`@dist1
- `hybrid` / `interface_shutdown` [OK] pred=`interface_down`@core1 truth=`interface_down`@core1
- `rule_only` / `interface_shutdown` [OK] pred=`interface_down`@core1 truth=`interface_down`@core1
- `llm_only` / `interface_shutdown` [MISS] pred=`acl_deny`@dist2 truth=`interface_down`@core1
- `hybrid` / `wrong_static_route` [OK] pred=`wrong_static_route`@core1 truth=`wrong_static_route`@core1
- `rule_only` / `wrong_static_route` [OK] pred=`wrong_static_route`@core1 truth=`wrong_static_route`@core1
- `llm_only` / `wrong_static_route` [MISS] pred=`acl_deny`@dist2 truth=`wrong_static_route`@core1
- `hybrid` / `ospf_passive_misconfig` [MISS] pred=`reachability_ok`@None truth=`missing_route`@dist2
- `rule_only` / `ospf_passive_misconfig` [MISS] pred=`reachability_ok`@None truth=`missing_route`@dist2
- `llm_only` / `ospf_passive_misconfig` [MISS] pred=`acl_deny`@dist2 truth=`missing_route`@dist2