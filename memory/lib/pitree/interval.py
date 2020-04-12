"""interval.py holds the Interval object, which is stored in an IntervalTree."""


class Interval(object):
    """Interval of memory addresses."""

    def __init__(self, begin, end, data=None):
        """
        Initialize an interval [begin, end].  (Presumably) inclusive range.

        :param begin: interval begin point
        :param end: interval end point
        :param data: interval maximum?
        """
        assert begin <= end
        self.begin = begin
        self.end = end
        self.data = data

    def containsPoint(self, point):
        """Determine whether a point is in this interval."""
        return self.begin < point and self.end >= point

    def overlap(self, other):
        """Determine whether two intervals overlap."""
        return not (self.begin >= other.end or self.end <= other.begin)

    def contains(self, other):
        """Determine if other is entirely contained within this interval."""
        return self.begin <= other.begin and self.end >= other.end

    def copy(self):
        """Copy an interval."""
        return Interval(self.begin, self.end, self.data)

    def __eq__(self, other):
        """Test interval equality."""
        return (self.begin == other.begin and
                self.end == other.end and
                self.data == other.data)

    def __ne__(self, other):
        """Test interval inequality."""
        return not self.__eq__(other)

    def __hash__(self):
        """Get the hash of an interval."""
        return hash((self.begin, self.end, self.data))

    def __str__(self):
        """Get the string representation of an interval."""
        return ("[" + str(self.begin) +
                ", " + str(self.end) + "] "
                + str(self.data))
