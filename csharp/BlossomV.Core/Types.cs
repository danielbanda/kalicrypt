namespace BlossomV.Core;

/// <summary>
/// Type definitions for Blossom V algorithm
/// Translated from C++ implementation
/// </summary>
public static class BlossomTypes
{
    // Use int for weights to match C++ implementation (REAL type without double precision)
    // Can be changed to double by defining PERFECT_MATCHING_DOUBLE
}

/// <summary>
/// Node identifier type
/// </summary>
public readonly struct NodeId
{
    public readonly int Value;

    public NodeId(int value) => Value = value;

    public static implicit operator NodeId(int value) => new(value);
    public static implicit operator int(NodeId id) => id.Value;

    public override string ToString() => Value.ToString();
}

/// <summary>
/// Edge identifier type
/// </summary>
public readonly struct EdgeId
{
    public readonly int Value;

    public EdgeId(int value) => Value = value;

    public static implicit operator EdgeId(int value) => new(value);
    public static implicit operator int(EdgeId id) => id.Value;

    public override string ToString() => Value.ToString();
}

/// <summary>
/// Real number type for costs/weights (can be int or double)
/// </summary>
public readonly struct Real
{
    public readonly int Value;

    public Real(int value) => Value = value;

    public static implicit operator Real(int value) => new(value);
    public static implicit operator int(Real real) => real.Value;

    public override string ToString() => Value.ToString();

    public static Real operator +(Real a, Real b) => new(a.Value + b.Value);
    public static Real operator -(Real a, Real b) => new(a.Value - b.Value);
    public static Real operator *(Real a, Real b) => new(a.Value * b.Value);
    public static Real operator /(Real a, Real b) => new(a.Value / b.Value);

    public static bool operator <(Real a, Real b) => a.Value < b.Value;
    public static bool operator >(Real a, Real b) => a.Value > b.Value;
    public static bool operator <=(Real a, Real b) => a.Value <= b.Value;
    public static bool operator >=(Real a, Real b) => a.Value >= b.Value;
    public static bool operator ==(Real a, Real b) => a.Value == b.Value;
    public static bool operator !=(Real a, Real b) => a.Value != b.Value;

    public override bool Equals(object? obj) => obj is Real other && Value == other.Value;
    public override int GetHashCode() => Value.GetHashCode();

    public static Real Max => new(int.MaxValue);
    public static Real Min => new(int.MinValue);
    public static Real Zero => new(0);
}
