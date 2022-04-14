
class Component:
    """
    Abstract class describing a satellite's component. Provides mass property information long with power and data usage.
    """

    def __init__(self, name, status=False, mass=0, xdim=0, ydim=0, zdim=0,
                 power_generation=0, power_usage=0, power_storage=0, power_capacity=0,
                 data_generation=0, data_usage=0, data_storage=0, data_capacity=0):
        """
        Initializes an abstract component. All values default to 0
        :param name: component name
        :param status: operational status of the component. 'True' for 'On' and 'False' for 'Off'
        :param mass: component's mass in [kg]
        :param xdim: component's dimension in the x-axis in [m]
        :param ydim: component's dimension in the y-axis in [m]
        :param zdim: component's dimension in the z-axis in [m]
        :param power_generation: how much power is generated by this component when on in [W]
        :param power_usage: how much power is consumed by this component when on in [W]
        :param power_stored: how much power is currently stored in this component in [J] aka [W*s]
        :param power_capacity: how much power can be stored in this component in [J] aka [W*s]
        :param data_generation: how much data is generated by this component when on in [Mbps]
        :param data_usage: how much data is consumed or transmitted by this component when on in [Mbps]
        :param data_stored: how much data is currently stored in this component in [Mb]
        :param data_capacity: how much data can be stored in this component in [Mb]
        """
        self.name = name
        self.status = status
        self.mass = mass
        self.dims = [xdim, ydim, zdim]
        self.power_generation = power_generation
        self.power_usage = power_usage
        self.power_stored = power_storage
        self.power_capacity = power_capacity
        self.data_generation = data_generation
        self.data_usage = data_usage
        self.data_stored = data_storage
        self.data_capacity = data_capacity

    def copy(self):
        """
        Creates a deep copy of this component
        :return:
        """
        return Component(self.status, self.mass, self.dims[0], self.dims[1], self.dims[2],
                         self.power_generation, self.power_usage, self.power_stored, self.power_capacity,
                         self.data_generation, self.data_usage, self.data_stored, self.data_capacity)

    def is_on(self) -> bool:
        """
        Returns status of the component
        :return:
        """
        return self.status

    def turn_on(self) -> None:
        """
        Turns on component
        :return: None
        """
        self.status = True
        return

    def turn_off(self) -> None:
        """
        Turns off component
        :return: None
        """
        self.status = False
        return

    def get_power_info(self):
        """
        Returns power information for this component
        :return: array containing in order: power generation, usage, storage, and capacity
        """
        return [self.power_generation, self.power_usage, self.power_stored, self.power_capacity]

    def get_data_info(self):
        """
        Returns data information for this component
        :return: array containing in order: data generation, usage, storage, and capacity
        """
        return [self.data_generation, self.data_usage, self.data_stored, self.data_capacity]

    def get_name(self):
        return self.name
