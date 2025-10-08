from provision import errors


def test_custom_errors_are_distinct():
    excs = [
        errors.RefuseSafeError,
        errors.HolderStuckError,
        errors.PartitionLayoutError,
        errors.FirmwareMissingError,
        errors.InitramfsError,
    ]
    instances = [exc("message") for exc in excs]
    assert all(isinstance(inst, Exception) for inst in instances)
    assert len({type(inst) for inst in instances}) == len(excs)
