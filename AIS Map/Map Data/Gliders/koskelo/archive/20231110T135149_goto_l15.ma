behavior_name=goto_list
# ADCPVM_goto_l10.ma for ADCPVM
# 2023-09-11 13:25  kimmo.tikka@fmi.fi  TVAR20232, ADCP triangle
# 2023-11-09 09:15  kimmo.tikka@fmi.fi  TVAR20233, Langskar East VM
# 2023-11-09 09:15  kimmo.tikka@fmi.fi  VM AJAX shipping
<start:b_arg>
b_arg: start_when(enum) 0 # 0-immediately, 1-stack idle 2-heading idle
b_arg: list_stop_when(enum) 7 # BAW_WHEN_WPT_DIST:007
b_arg: initial_wpt(enum)        -2   #! min = -2; max = 7
                                     # Which waypoint to head for first
                                     #  0 to N-1 the waypoint in the list
                                     # -1 ==> one after last one achieved
                                     # -2 ==> closest
b_arg: num_legs_to_run(nodim)   -2   #  1-N    exactly this many waypoints
                                     #  0      illegal
                                     # -1      loop forever
                                     # -2      traverse list once (stop at last in list)
                                     # <-2     illegal
b_arg: num_waypoints(nodim) 1
<end:b_arg>
<start:waypoints>
#WPT FORMAT: (DDmm.mmm)
# longitude latitude # koodi nimi
2314.05 5944.71   # ajax_vmn 
<end:waypoints>
