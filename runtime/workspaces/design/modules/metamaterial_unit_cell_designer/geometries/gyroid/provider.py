"""Legacy sheet uses the dedicated writer; field representations are opt-in."""


def generate_field(grid, request):
    raise ValueError("Gyroid sheet uses the legacy writer adapter, not a replacement field")
