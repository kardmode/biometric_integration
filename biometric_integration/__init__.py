__version__ = "0.0.1"


def _patch_hrms():
	try:
		from biometric_integration.biometric_integration.overrides import apply_hrms_patches
		apply_hrms_patches()
	except Exception:
		pass


_patch_hrms()
