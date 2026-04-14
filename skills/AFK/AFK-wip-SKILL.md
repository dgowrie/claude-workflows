you are going to start an AFK task. here is the context:                                                                              
                                                                                                                                        
# Span control UI - status and next steps                                                                                               
                                                                                                                                        
## PRD                                                                                                                                  
https://github.com/grafana/grafana-adaptivetraces-app/issues/685                                                                        
                                                                                                                                        
Read the PRD and its sub-issues for detailed context on the feature, user stories, and requirements. The PRD is the source of truth for 
 what we're building and why.                                                                                                           
                                                                                                                                        
## Implementation plan summary                                                                                                          
                                                                                                                                        
4 phases, each a shippable increment. Plans are in `docs/span-control-features/`:                                                       
- `span-control-ui-prototype-plan.md` - component architecture, phased delivery, design decisions                                       
- `impact-metrics-ui-final-plan.md` - SceneImpactMetrics component, metric contract, PromQL queries                                     
                                                                                                                                        
## Concurrency plan                                                                                                                     
                                                                                                                                        
| Worktree | Work | Issue | Depends on |                                                                                                
|----------|------|-------|------------|                                                                                                
| A | Phase 1: feature flags, config type, SpanControlSection + Row + SemconvFeatureCard on Overview | #686 | #691 merged |             
| B | SceneImpactMetrics standalone component (Scenes panels, grafanacloud-usage queries) | #688 (partial) | Nothing beyond flag type | 
                                                                                                                                        
Phase 1 is the critical path. SceneImpactMetrics is genuinely independent - it follows the SceneBigNumbers pattern and only needs the   
`impactMetrics` flag type added.                                                                                                        
                                                                                                                                        
## After A and B merge                                                                                                                  
                                                                                                                                        
- Phase 2 (#687) + Phase 3 embedding (#688 remainder) as a single PR: SemconvDrawer with status, examples, doc links, and               
SceneImpactMetrics embedded                                                                                                             
- Phase 4 (#689): interactive toggle with ConfirmModal and `usePutConfigMutation`                                                       
                                                                                                                                        
## Key blockers / open questions                                                                                                        
                                                                                                                                        
- **F11**: Confirm whether backend applies full OTel semconv spec or a subset (blocks Phase 2 example accuracy) - ask infra/Yuna        
- **F12**: Impact metrics recording rule prod rollout (blocks enabling `impactMetrics` flag in prod) - coordinate with infra            
- **F15**: Definition of "transformed" in `preprocessing_spans_transformed_total` - ask infra/Yuna                                      
- **Feature flag registration**: `adapt_tel.traces.spanControl` and `adapt_tel.traces.impactMetrics` need OpenFeature backend           
registration before prod enablement                                                                                                     
                                                                                                                                        
In this session, you will handle Worktree B (as described above). Another session will handle Worktree A. Any concerns or questions     
before beginning your work? Be sure to read the global CLAUDE.md file.   