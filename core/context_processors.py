from .models import LabInfo


def lab_info(request):
    """Make the lab's name, address and hours available to every page, for the footer (SXFT-16)."""
    return {"lab_info": LabInfo.load()}