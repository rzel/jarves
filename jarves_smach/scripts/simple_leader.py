#!/usr/bin/env python

import roslib

roslib.load_manifest('jarves')
roslib.load_manifest('uashh_smach')

import rospy
import numpy
import smach
import smach_ros
from smach import State, Sequence
from smach_ros import SimpleActionState, ServiceState

from move_base_msgs.msg import MoveBaseGoal, MoveBaseAction
from geometry_msgs.msg import Pose, PoseStamped, PoseWithCovarianceStamped

from uashh_smach.util import WaitForMsgState

def poseDistance(pose1, pose2):
    x1 = pose1.pose.pose.position.x
    y1 = pose1.pose.pose.position.y
    x2 = pose2.pose.pose.position.x
    y2 = pose2.pose.pose.position.y
    a = numpy.array(x1, y1)
    b = numpy.array(x2, y2)
    distance = numpy.linalg.norm(a-b)
    return distance

class WaitForGoalMsgState(WaitForMsgState):
    """Waits for goal message to save to userdata"""
    def __init__(self, goal_topic='move_base_simple/goal'):
        WaitForMsgState.__init__(self, goal_topic, PoseStamped, self._msg_cb, output_keys=['goal'])#, latch=True, timeout=5)

    def _msg_cb(self, msg, ud):
        goal = MoveBaseGoal()
        goal.target_pose.pose = msg.pose.pose
        goal.target_pose.header.frame_id = msg.header.frame_id
        goal.target_pose.header.stamp = msg.header.stamp
        ud.goal = msg

class WaitForPoseMsgState(WaitForMsgState):
    """Waits for pose message to save to userdata"""
    def __init__(self, pose_topic='pose', pose_id='pose'):
        WaitForMsgState.__init__(self, pose_topic, PoseWithCovarianceStamped, self._msg_cb, output_keys=[pose_id])#, latch=True)
        self.pose_id = pose_id

    def _msg_cb(self, msg, ud):
        setattr(ud, self.pose_id, msg)

class MoveBaseToGoalState(SimpleActionState):
    """Calls a move_base action server using goal from userdata"""
    def __init__(self, movebase_ns='move_base'):
        SimpleActionState.__init__(self, movebase_ns, MoveBaseAction, input_keys=['goal'], goal_cb=self.__goal_cb)

    def __goal_cb(self, ud):
        return ud.goal

class MoveBaseToFollowerState(SimpleActionState):
    """Calls a move_base action server using follower pose from userdata"""
    def __init__(self, movebase_ns='move_base'):
        SimpleActionState.__init__(self, movebase_ns, MoveBaseAction, input_keys=['follower'], goal_cb=self.__goal_cb)

    def __goal_cb(self, ud):
        goal = MoveBaseGoal()
        goal.target_pose.pose = ud.follower.pose.pose
        goal.target_pose.header.frame_id = ud.follower.header.frame_id
        goal.target_pose.header.stamp = ud.follower.header.stamp
        return goal

class ChooseFocusState(smach.State):
    """Chooses to focus on goal or follower using userdata"""
    def __init__(self):
        smach.State.__init__(self, outcomes=['goal','follower','done','wait'])

    def execute(self, ud):
        rospy.loginfo('Executing state ChooseFocusState')
        if((ud.goal is None) or (ud.leader is None) or (ud.follower is None)):
            return 'wait'
        follower_distance = poseDistance(ud.leader, ud.follower)
        goal_distance = poseDistance(ud.leader, ud.follower)
        if(follower_distance > ud.upper_follower_threshold):
            return 'follower'
        elif(follower_distance < ud.lower_follower_threshold):
            return 'goal'
        elif(goal_distance < ud.lower_goal_threshold):
            return 'done'

# main
def simple_leader():
    rospy.init_node('simple_lead')
    goal_topic = rospy.get_param('~goal_topic', 'move_base_simple/goal')
    leader_topic = rospy.get_param('~leader_topic', 'pose')
    follower_topic = rospy.get_param('~follower_topic', 'pose')
    movebase_ns = rospy.get_param('~movebase_ns', 'move_base')

    # rospy.loginfo(rospy.get_caller_id() + " goal_topic:" + goal_topic)
    # rospy.loginfo(rospy.get_caller_id() + " follower_topic:" + follower_topic)
    # rospy.loginfo(rospy.get_caller_id() + " movebase_ns:" + movebase_ns)

    # Create the top level SMACH state machine
    sm = smach.StateMachine(outcomes=['woot'])
    sm.userdata.goal = None
    sm.userdata.leader = None
    sm.userdata.follower = None
    sm.userdata.upper_follower_threshold = 3
    sm.userdata.lower_follower_threshold = 2
    sm.userdata.lower_goal_threshold = 1

    # Open the container
    with sm:
        smach.StateMachine.add('INIT_GOAL', WaitForGoalMsgState(goal_topic),
                                transitions={'succeeded':'CON',
                                             'preempted':'CON',
                                             'aborted':'CON'})

        # Create the sub SMACH state machine
        sm_con = smach.Concurrence(outcomes=['succeeded'],
                                   default_outcome='succeeded',
                                   outcome_map={'succeeded':
                                       { 'CHECK_GOAL':'succeeded',
                                         'CHECK_LEADER':'succeeded',
                                         'CHECK_FOLLOWER':'succeeded'}})

        # Open the container
        with sm_con:
            # Add states to the container
            smach.Concurrence.add('CHECK_GOAL', WaitForGoalMsgState(goal_topic))
            smach.Concurrence.add('CHECK_LEADER', WaitForPoseMsgState(leader_topic, 'leader'))
            smach.Concurrence.add('CHECK_FOLLOWER', WaitForPoseMsgState(follower_topic), 'follower')

        smach.StateMachine.add('CON', sm_con,
                               transitions={'succeeded':'CHECK_FOCUS'})

        smach.StateMachine.add('SEEK_FOLLOWER', MoveBaseToFollowerState(movebase_ns),
                                transitions={'succeeded':'CON',
                                             'preempted':'CON',
                                             'aborted':'CON'})
        smach.StateMachine.add('SEEK_GOAL', MoveBaseToGoalState(movebase_ns),
                                transitions={'succeeded':'CON',
                                             'preempted':'CON',
                                             'aborted':'CON'})
        smach.StateMachine.add('CHECK_FOCUS', ChooseFocusState(),
                                transitions={'wait':'CON',
                                             'follower':'SEEK_FOLLOWER',
                                             'goal':'SEEK_GOAL',
                                             'done':'woot'})
    # Create and start the introspection server
    sis = smach_ros.IntrospectionServer('simple_lead_sis', sm, '/')
    sis.start()

    # Execute SMACH plan
    outcome = sm.execute()
    rospy.spin()
    sis.stop()

if __name__ == '__main__':
    simple_leader()
