"""Non-eucentric rotation: orbit model and the image processing that tracks a sample.

``orbit`` predicts where a sample sits (CoarseY, SampleX, ZonePlateZ) at each CoarseR
angle; ``imaging`` finds how far a measured image is from that prediction.  Neither
touches hardware, so both run offline and under test.
"""
