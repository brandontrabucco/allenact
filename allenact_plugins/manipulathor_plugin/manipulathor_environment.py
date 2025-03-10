"""A wrapper for engaging with the ManipulaTHOR environment."""

import copy
import math
import warnings
from typing import Dict, Union, Any, Optional, cast

import ai2thor.server
import numpy as np
import math

from ai2thor.controller import Controller
from allenact.utils.misc_utils import prepare_locals_for_super

from allenact_plugins.ithor_plugin.ithor_constants import VISIBILITY_DISTANCE, FOV
from allenact_plugins.ithor_plugin.ithor_environment import IThorEnvironment
from allenact_plugins.manipulathor_plugin.armpointnav_constants import (
    MOVE_ARM_HEIGHT_CONSTANT,
    MOVE_ARM_CONSTANT,
    UNWANTED_MOVE_THR,
    DISTANCE_MAX,
)

from allenact_plugins.manipulathor_plugin.manipulathor_constants import (
    ADDITIONAL_ARM_ARGS,
    ARM_MIN_HEIGHT,
    ARM_MAX_HEIGHT,
)

from allenact_plugins.manipulathor_plugin.manipulathor_constants import (
    MOVE_ARM_HEIGHT_P,
    MOVE_ARM_HEIGHT_M,
    MOVE_ARM_X_P,
    MOVE_ARM_X_M,
    MOVE_ARM_Y_P,
    MOVE_ARM_Y_M,
    MOVE_ARM_Z_P,
    MOVE_ARM_Z_M,
    ROTATE_WRIST_PITCH_P,
    ROTATE_WRIST_PITCH_M,
    ROTATE_WRIST_YAW_P,
    ROTATE_WRIST_YAW_M,
    ROTATE_ELBOW_P,
    ROTATE_ELBOW_M,
    LOOK_UP,
    LOOK_DOWN,
    MOVE_AHEAD,
    ROTATE_RIGHT,
    ROTATE_LEFT,
    PICKUP,
    DONE,
)

from allenact_plugins.manipulathor_plugin.manipulathor_utils import (
    reset_environment_and_additional_commands,
)


def position_distance(s1, s2, filter_nan: bool = False):
    position1 = s1["position"]
    position2 = s2["position"]
    dist = (
        (position1["x"] - position2["x"]) ** 2
        + (position1["y"] - position2["y"]) ** 2
        + (position1["z"] - position2["z"]) ** 2
    ) ** 0.5
    if filter_nan:
        dist = DISTANCE_MAX if math.isnan(dist) or dist > DISTANCE_MAX else dist
    return dist


def rotation_distance(s1: Dict[str, float], s2: Dict[str, float]):
    """Distance between rotations."""
    rotation1 = s1["rotation"]
    rotation2 = s2["rotation"]

    def deg_dist(d0: float, d1: float):
        dist = (d0 - d1) % 360
        return min(dist, 360 - dist)

    return sum(deg_dist(rotation1[k], rotation2[k]) for k in ["x", "y", "z"])


class ManipulaTHOREnvironment(IThorEnvironment):
    """Wrapper for the manipulathor controller providing arm functionality
    and bookkeeping.

    See [here](https://ai2thor.allenai.org/documentation/installation) for comprehensive
     documentation on AI2-THOR.

    # Attributes

    controller : The ai2thor controller.
    """

    def __init__(
        self,
        x_display: Optional[str] = None,
        docker_enabled: bool = False,
        local_thor_build: Optional[str] = None,
        visibility_distance: float = VISIBILITY_DISTANCE,
        fov: float = FOV,
        player_screen_width: int = 224,
        player_screen_height: int = 224,
        quality: str = "Very Low",
        restrict_to_initially_reachable_points: bool = False,
        make_agents_visible: bool = True,
        object_open_speed: float = 1.0,
        simplify_physics: bool = False,
        verbose: bool = False,
        env_args=None,
    ) -> None:
        """Initializer.

        # Parameters

        x_display : The x display into which to launch ai2thor (possibly necessarily if you are running on a server
            without an attached display).
        docker_enabled : Whether or not to run thor in a docker container (useful on a server without an attached
            display so that you don't have to start an x display).
        local_thor_build : The path to a local build of ai2thor. This is probably not necessary for your use case
            and can be safely ignored.
        visibility_distance : The distance (in meters) at which objects, in the viewport of the agent,
            are considered visible by ai2thor and will have their "visible" flag be set to `True` in the metadata.
        fov : The agent's camera's field of view.
        width : The width resolution (in pixels) of the images returned by ai2thor.
        height : The height resolution (in pixels) of the images returned by ai2thor.
        quality : The quality at which to render. Possible quality settings can be found in
            `ai2thor._quality_settings.QUALITY_SETTINGS`.
        restrict_to_initially_reachable_points : Whether or not to restrict the agent to locations in ai2thor
            that were found to be (initially) reachable by the agent (i.e. reachable by the agent after resetting
            the scene). This can be useful if you want to ensure there are only a fixed set of locations where the
            agent can go.
        make_agents_visible : Whether or not the agent should be visible. Most noticable when there are multiple agents
            or when quality settings are high so that the agent casts a shadow.
        object_open_speed : How quickly objects should be opened. High speeds mean faster simulation but also mean
            that opening objects have a lot of kinetic energy and can, possibly, knock other objects away.
        simplify_physics : Whether or not to simplify physics when applicable. Currently this only simplies object
            interactions when opening drawers (when simplified, objects within a drawer do not slide around on
            their own when the drawer is opened or closed, instead they are effectively glued down).
        """
        self._verbose = verbose
        self.env_args = env_args
        del verbose
        del env_args
        super(ManipulaTHOREnvironment, self).__init__(
            **prepare_locals_for_super(locals())
        )

    def create_controller(self):
        controller = Controller(**self.env_args)

        return controller

    def start(
        self, scene_name: Optional[str], move_mag: float = 0.25, **kwargs,
    ) -> None:
        """Starts the ai2thor controller if it was previously stopped.

        After starting, `reset` will be called with the scene name and move magnitude.

        # Parameters

        scene_name : The scene to load.
        move_mag : The amount of distance the agent moves in a single `MoveAhead` step.
        kwargs : additional kwargs, passed to reset.
        """
        if self._started:
            raise RuntimeError(
                "Trying to start the environment but it is already started."
            )

        self.controller = self.create_controller()

        self._started = True
        self.reset(scene_name=scene_name, move_mag=move_mag, **kwargs)

    def reset(
        self, scene_name: Optional[str], move_mag: float = 0.25, **kwargs,
    ):
        self._move_mag = move_mag
        self._grid_size = self._move_mag

        if scene_name is None:
            scene_name = self.controller.last_event.metadata["sceneName"]
        # self.reset_init_params()#**kwargs) removing this fixes one of the crashing problem

        # to solve the crash issue
        # TODO why do we still have this crashing problem?
        try:
            reset_environment_and_additional_commands(self.controller, scene_name)
        except Exception as e:
            print("RESETTING THE SCENE,", scene_name, "because of", str(e))
            self.controller = ai2thor.controller.Controller(**self.env_args)
            reset_environment_and_additional_commands(self.controller, scene_name)

        if self.object_open_speed != 1.0:
            self.controller.step(
                {"action": "ChangeOpenSpeed", "x": self.object_open_speed}
            )

        self._initially_reachable_points = None
        self._initially_reachable_points_set = None
        self.controller.step({"action": "GetReachablePositions"})
        if not self.controller.last_event.metadata["lastActionSuccess"]:
            warnings.warn(
                "Error when getting reachable points: {}".format(
                    self.controller.last_event.metadata["errorMessage"]
                )
            )
        self._initially_reachable_points = self.last_action_return

        self.list_of_actions_so_far = []

    def randomize_agent_location(
        self, seed: int = None, partial_position: Optional[Dict[str, float]] = None
    ) -> Dict:
        raise NotImplementedError

    def is_object_at_low_level_hand(self, object_id):
        current_objects_in_hand = self.controller.last_event.metadata["arm"][
            "heldObjects"
        ]
        return object_id in current_objects_in_hand

    def object_in_hand(self):
        """Object metadata for the object in the agent's hand."""
        inv_objs = self.last_event.metadata["inventoryObjects"]
        if len(inv_objs) == 0:
            return None
        elif len(inv_objs) == 1:
            return self.get_object_by_id(
                self.last_event.metadata["inventoryObjects"][0]["objectId"]
            )
        else:
            raise AttributeError("Must be <= 1 inventory objects.")

    def correct_nan_inf(self, flawed_dict, extra_tag=""):
        corrected_dict = copy.deepcopy(flawed_dict)
        for (k, v) in corrected_dict.items():
            if math.isnan(v) or math.isinf(v):
                corrected_dict[k] = 0
        return corrected_dict

    def get_object_by_id(self, object_id: str) -> Optional[Dict[str, Any]]:
        for o in self.last_event.metadata["objects"]:
            if o["objectId"] == object_id:
                o["position"] = self.correct_nan_inf(o["position"], "obj id")
                return o
        return None

    def get_current_arm_state(self):
        h_min = ARM_MIN_HEIGHT
        h_max = ARM_MAX_HEIGHT
        agent_base_location = 0.9009995460510254
        event = self.controller.last_event
        offset = event.metadata["agent"]["position"]["y"] - agent_base_location
        h_max += offset
        h_min += offset
        joints = event.metadata["arm"]["joints"]
        arm = joints[-1]
        assert arm["name"] == "robot_arm_4_jnt"
        xyz_dict = copy.deepcopy(arm["rootRelativePosition"])
        height_arm = joints[0]["position"]["y"]
        xyz_dict["h"] = (height_arm - h_min) / (h_max - h_min)
        xyz_dict = self.correct_nan_inf(xyz_dict, "realtive hand")
        return xyz_dict

    def get_absolute_hand_state(self):
        event = self.controller.last_event
        joints = event.metadata["arm"]["joints"]
        arm = copy.deepcopy(joints[-1])
        assert arm["name"] == "robot_arm_4_jnt"
        xyz_dict = arm["position"]
        xyz_dict = self.correct_nan_inf(xyz_dict, "absolute hand")
        return dict(position=xyz_dict, rotation={"x": 0, "y": 0, "z": 0})

    def get_pickupable_objects(self):

        event = self.controller.last_event
        object_list = event.metadata["arm"]["pickupableObjects"]

        return object_list

    def get_current_object_locations(self):
        obj_loc_dict = {}
        metadata = self.controller.last_event.metadata["objects"]
        for o in metadata:
            obj_loc_dict[o["objectId"]] = dict(
                position=o["position"], rotation=o["rotation"], visible=o["visible"],
            )
        return copy.deepcopy(obj_loc_dict)

    def close_enough(self, current_obj_pose, init_obj_pose, threshold):
        position_close = [
            abs(current_obj_pose["position"][k] - init_obj_pose["position"][k])
            <= threshold
            for k in ["x", "y", "z"]
        ]
        position_is_close = sum(position_close) == 3
        return position_is_close

    def get_objects_moved(
        self,
        previous_object_locations,
        current_object_locations,
        target_object_id,
        thres_dict: Optional[Dict] = None,
    ):
        moved_objects = []
        scene_id = self.scene_name.split("_")[0]

        for object_id in current_object_locations.keys():
            if object_id == target_object_id:
                continue
            if object_id not in previous_object_locations:
                continue

            threshold = UNWANTED_MOVE_THR
            if thres_dict is not None:
                threshold = max(threshold, thres_dict[scene_id + "-" + object_id])

            if not self.close_enough(
                current_object_locations[object_id],
                previous_object_locations[object_id],
                threshold=threshold,
            ):
                moved_objects.append(object_id)

        return moved_objects

    def get_objects_move_distance(
        self,
        initial_object_locations,
        previous_object_locations,
        current_object_locations,
        target_object_id,
        only_visible: bool = False,
        thres_dict: Optional[Dict] = None,
    ):
        moved_objects_position_distance = {}
        scene_id = self.scene_name.split("_")[0]

        for object_id in current_object_locations.keys():
            if object_id == target_object_id:
                continue
            if object_id not in previous_object_locations:
                continue
            if only_visible:
                # current is visible
                if not current_object_locations[object_id]["visible"]:
                    continue

            p_initial2current = position_distance(
                current_object_locations[object_id],
                initial_object_locations[object_id],
                filter_nan=True,
            )
            p_initial2previous = position_distance(
                previous_object_locations[object_id],
                initial_object_locations[object_id],
                filter_nan=True,
            )

            threshold = 0.0
            if thres_dict is not None:
                threshold = max(threshold, thres_dict[scene_id + "-" + object_id])

            p_initial2current = max(0.0, p_initial2current - threshold)
            p_initial2previous = max(0.0, p_initial2previous - threshold)

            moved_objects_position_distance[object_id] = (
                p_initial2current - p_initial2previous
            )

        return sum(moved_objects_position_distance.values())

    def step(
        self, action_dict: Dict[str, Union[str, int, float]]
    ) -> ai2thor.server.Event:
        """Take a step in the ai2thor environment."""
        action = cast(str, action_dict["action"])

        skip_render = "renderImage" in action_dict and not action_dict["renderImage"]
        last_frame: Optional[np.ndarray] = None
        if skip_render:
            last_frame = self.current_frame

        if self.simplify_physics:
            action_dict["simplifyOPhysics"] = True
        if action in [PICKUP, DONE]:
            if action == PICKUP:
                object_id = action_dict["object_id"]
                if not self.is_object_at_low_level_hand(object_id):
                    pickupable_objects = self.get_pickupable_objects()
                    #
                    if object_id in pickupable_objects:
                        # This version of the task is actually harder # consider making it easier, are we penalizing failed pickup? yes
                        self.step(dict(action="PickupObject"))
                        #  we are doing an additional pass here, label is not right and if we fail we will do it twice
                        object_inventory = self.controller.last_event.metadata["arm"][
                            "heldObjects"
                        ]
                        if (
                            len(object_inventory) > 0
                            and object_id not in object_inventory
                        ):
                            self.step(dict(action="ReleaseObject"))
            action_dict = {"action": "Pass"}

        elif action in [MOVE_AHEAD, ROTATE_LEFT, ROTATE_RIGHT]:
            copy_additions = copy.deepcopy(ADDITIONAL_ARM_ARGS)

            action_dict = {**action_dict, **copy_additions}
            if action in [MOVE_AHEAD]:
                action_dict["action"] = "MoveAgent"
                action_dict["ahead"] = 0.2

            elif action in [ROTATE_RIGHT]:
                action_dict["action"] = "RotateAgent"
                action_dict["degrees"] = 45

            elif action in [ROTATE_LEFT]:
                action_dict["action"] = "RotateAgent"
                action_dict["degrees"] = -45

        elif "MoveArm" in action:
            copy_additions = copy.deepcopy(ADDITIONAL_ARM_ARGS)
            action_dict = {**action_dict, **copy_additions}
            base_position = self.get_current_arm_state()
            if "MoveArmHeight" in action:
                action_dict["action"] = "MoveArmBase"

                if action == "MoveArmHeightP":
                    base_position["h"] += MOVE_ARM_HEIGHT_CONSTANT
                if action == "MoveArmHeightM":
                    base_position[
                        "h"
                    ] -= MOVE_ARM_HEIGHT_CONSTANT  # height is pretty big!
                action_dict["y"] = base_position["h"]
            else:
                action_dict["action"] = "MoveArm"
                if action == "MoveArmXP":
                    base_position["x"] += MOVE_ARM_CONSTANT
                elif action == "MoveArmXM":
                    base_position["x"] -= MOVE_ARM_CONSTANT
                elif action == "MoveArmYP":
                    base_position["y"] += MOVE_ARM_CONSTANT
                elif action == "MoveArmYM":
                    base_position["y"] -= MOVE_ARM_CONSTANT
                elif action == "MoveArmZP":
                    base_position["z"] += MOVE_ARM_CONSTANT
                elif action == "MoveArmZM":
                    base_position["z"] -= MOVE_ARM_CONSTANT
                action_dict["position"] = {
                    k: v for (k, v) in base_position.items() if k in ["x", "y", "z"]
                }

        elif "RotateArm" in action:
            copy_additions = copy.deepcopy(ADDITIONAL_ARM_ARGS)
            action_dict = {**action_dict, **copy_additions}

            if action == ROTATE_WRIST_PITCH_P:
                action_dict["action"] = "RotateWristRelative"
                action_dict["pitch"] = 15
            elif action == ROTATE_WRIST_PITCH_M:
                action_dict["action"] = "RotateWristRelative"
                action_dict["pitch"] = -15
            elif action == ROTATE_WRIST_YAW_P:
                action_dict["action"] = "RotateWristRelative"
                action_dict["yaw"] = 15
            elif action == ROTATE_WRIST_YAW_M:
                action_dict["action"] = "RotateWristRelative"
                action_dict["yaw"] = -15
            elif action == ROTATE_ELBOW_P:
                action_dict["action"] = "RotateElbowRelative"
                action_dict["degrees"] = 15
            elif action == ROTATE_ELBOW_M:
                action_dict["action"] = "RotateElbowRelative"
                action_dict["degrees"] = -15
            else:
                raise ValueError("invalid action " + str(action))

        elif action in [LOOK_UP, LOOK_DOWN]:
            copy_additions = copy.deepcopy(ADDITIONAL_ARM_ARGS)
            action_dict = {**action_dict, **copy_additions}
            if action == LOOK_UP:
                action_dict["action"] = LOOK_UP
            elif action == LOOK_DOWN:
                action_dict["action"] = LOOK_DOWN

        # there exists other actions e.g. "PlaceObjectAtPoint"

        sr = self.controller.step(action_dict)
        self.list_of_actions_so_far.append(action_dict)

        if self._verbose:
            print(self.controller.last_event)

        if self.restrict_to_initially_reachable_points:
            self._snap_agent_to_initially_reachable()

        if skip_render:
            assert last_frame is not None
            self.last_event.frame = last_frame

        return sr
