#!/usr/bin/env python

import rospy
import math
import actionlib
import numpy as np
import time

from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import Pose, Point, Quaternion
from visualization_msgs.msg import Marker, MarkerArray
from std_msgs.msg import ColorRGBA
from geometry_msgs.msg import Vector3
from nav_msgs.msg import OccupancyGrid
from sensor_msgs.msg import LaserScan
from tf.transformations import quaternion_from_euler

"""
This version of the planner takes into account
the laserscan messages instead of the costmap.

The main difference for this version of the 
unknown area planner is that it takes into
account the current data instead of the data
that is already in the costmap

The sparse matrix that arises from using the costmap
slows down computation and is much harder to perform
calculations on due to its grid-like style rather than
using distances and the angle at which those distances
were taken.
"""

# Weight constants for calculating the vectors
K = 0.0005
FORWARD_WEIGHT_D = 0.04

# Safety tolerance, the kart cannot be this close to
# another obstacle (meters)
SAFETY_TOLERANCE = 0.1

# Update rate for the goal, this should be dependent
# on the incoming messages. (in seconds)
UPDATE_RATE = 0.45

# Debug flag for use in displaying extra information
# to rviz. If true debugging information will be shown.
DEBUG_FLAG = True

"""
This function goes into effect when a new laserscan message is taken
from the ROS system. With each new message this function sends a new
movement goal based on potential field avoidance and obstacle collision.
"""
def callback(laserscan):
    # Create the action client that sends messages to move base
    client = actionlib.SimpleActionClient("move_base", MoveBaseAction)

    # Wait for initialization of the action client
    client.wait_for_server()

    # Initialize the move base goal message to be sent
    goal = MoveBaseGoal()

    # Calculate the movement vectors from the potential field function
    vec_x, vec_y = compute_vector_field(laserscan)
    print(vec_x, vec_y)

    # Fill in the message with header information and the movement vectors
    goal.target_pose.header.frame_id = "base_link"
    goal.target_pose.header.stamp = rospy.Time.now()
    goal.target_pose.pose.position.x = vec_x
    goal.target_pose.pose.position.y = vec_y
    goal.target_pose.pose.orientation = Quaternion(*(quaternion_from_euler(0, 0, math.atan2(vec_y, vec_x), axes='sxyz')))

    # Send the goal and sleep while the goal is followed
    # The sleep prevents a "stop and go" behavior and instead
    # calculates the vectors as the kart is moving
    client.send_goal(goal)
    time.sleep(UPDATE_RATE)


"""
This should be the main function running, as it receives
laserscan messages it should interrupt and perform the operations
on the vector field.
"""
def laserscan_listener():
    rospy.init_node("move_base_sequence", anonymous=True)
    rospy.Subscriber("scan", LaserScan, callback, queue_size=1)
    rospy.spin()


"""
This function computes the vector field that is created
by the objects in the distance and the resultant vector
components that will be safe to act upon when moving the kart
"""
def compute_vector_field(laserscan):
    angle_min = laserscan.angle_min
    angle_max = laserscan.angle_max

    ranges = np.array(laserscan.ranges)

    # Create an array to hold the angles
    theta_arr = np.linspace(start=round(angle_min + math.pi, 6), stop=round(angle_max + math.pi, 6), num=len(ranges))

    # Calculate the x & y components for the given information
    x_vector_comp = np.multiply(np.divide(K, np.square(ranges)), np.cos(theta_arr))
    y_vector_comp = np.multiply(np.divide(K, np.square(ranges)), np.sin(theta_arr))

    # Sum the vectors
    x_vec = np.sum(x_vector_comp)
    y_vec = np.sum(y_vector_comp)

    # Add a weight for the kart to move forward
    forward_weight_mag = (K / (FORWARD_WEIGHT_D ** 2))
    x_vec += forward_weight_mag * math.cos(0)
    y_vec += forward_weight_mag * math.sin(0)

    # verify the vector is safe and move if so, otherwise give zero vector
    if verify_vector(laserscan, (x_vec, y_vec)):
        if DEBUG_FLAG:
            visualize_field(x_vector_comp, y_vector_comp, ranges, theta_arr)
        # return the vectors as a zipped tuple
        return (x_vec, y_vec)
    else:
        return (0, 0)

"""
The importance of this function is that it verifies that once
the vector is generated, nothing is in the way of the kart
and that the vector is safe to act upon.

To be extra safe, every range finding is checked to make sure
that the kart will not be hitting the possible object in the distance
"""
def verify_vector(laserscan, mov_vec):
    angle_min = laserscan.angle_min
    angle_max = laserscan.angle_max
    angle_incr = laserscan.angle_increment

    ranges = np.array(laserscan.ranges)

    # Create an array to hold the angles
    theta_arr = np.arange(start=round(angle_min, 6), stop=round(angle_max, 6),
                          step=round(angle_incr, 6), dtype=np.float)

    # Unpack the given movement vector
    vec_x, vec_y = mov_vec

    # Calculate the magnitude and angle of the given vector
    vec_mag = math.sqrt((vec_x ** 2) + (vec_y ** 2))
    vec_theta = math.atan2(vec_y, vec_x)

    # Check each range at each angle, to actually test the distance a few
    # things will be checked. The first of which is if the vector is through
    # an object. The second is if the kart is too close to the obstacle
    # For the first part this can be done by creating a line segment perpendicular
    # to the movement vector of size SAFETY_TOLERANCE and checking for intersection
    # for dist in np.nditer(theta_arr):
    # TODO: Evaluate need for verification of vector if nav stack provides support
    return True


"""
This function displays the vector field into a pose array
that can be viewed in RVIZ. This should only be used for debugging
purposes as it can be costly to run RVIZ while the kart is actually
running.
"""
def visualize_field(x_vec_arr, y_vec_arr, ranges, theta_arr):

    # Create a publisher for the rostopic 'vector_field'
    # this will publish the marker array messages
    publisher = rospy.Publisher('vector_field', MarkerArray)

    vec_field = MarkerArray()

    # Variable used to ID each marker in the array
    i = 0

    # Iterate through the following arrays and add markers to the marker array
    # message to be sent
    for r, theta, x_or, y_or in np.nditer([ranges, theta_arr, x_vec_arr, y_vec_arr]):
        # Initialize a marker message
        _marker = Marker()

        # Populate the pose field of the marker message
        _marker.pose.position.x = r * math.cos(theta + math.pi)
        _marker.pose.position.y = r * math.sin(theta + math.pi)
        _marker.pose.position.z = 0

        _marker.pose.orientation = Quaternion(*(quaternion_from_euler(0, 0, math.atan2(y_or, x_or) + math.pi, 'sxyz')))

        # Populate the scale field of the marker message
        _marker.scale.x = 2000 * x_or
        _marker.scale.y = 2000 * y_or
        _marker.scale.z = 0.0001

        # Populate the color field of the marker message -> teal
        _marker.color.r = 0
        _marker.color.g = 128
        _marker.color.b = 128
        _marker.color.a = 255

        # Populate the header of the marker message
        _marker.header.stamp.secs = rospy.Time.now().secs
        _marker.header.stamp.nsecs = rospy.Time.now().nsecs
        _marker.header.frame_id = "base_link"
        _marker.header.seq = i

        _marker.ns = "cur_marker"
        _marker.id = i

        i += 1

        _marker.type = 0
        _marker.lifetime.secs = UPDATE_RATE
        _marker.frame_locked = False

        # Append the marker message to the list of markers
        vec_field.markers.append(_marker)

    # Publish the marker array
    publisher.publish(vec_field)


if __name__ == "__main__":
    try:
        laserscan_listener()
    except rospy.ROSInterruptException:
        rospy.loginfo("Navigation Complete.")