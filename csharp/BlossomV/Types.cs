namespace BlossomV;

/// <summary>
/// Type aliases matching the Rust implementation
/// Using uint for indices (equivalent to u32 or usize in Rust)
/// Using int for weights (equivalent to i32 or isize in Rust)
/// </summary>
public static class Types
{
    // Type aliases for clarity and consistency with Rust implementation
    public const int MaxSafeWeight = int.MaxValue;
}

/// <summary>
/// Weight type (equivalent to i32 or isize in Rust)
/// </summary>
public readonly struct Weight
{
    public readonly int Value;

    public Weight(int value)
    {
        Value = value;
    }

    public static implicit operator Weight(int value) => new Weight(value);
    public static implicit operator int(Weight weight) => weight.Value;

    public override string ToString() => Value.ToString();
}

/// <summary>
/// Vertex index type (equivalent to u32 or usize in Rust)
/// </summary>
public readonly struct VertexIndex
{
    public readonly uint Value;

    public VertexIndex(uint value)
    {
        Value = value;
    }

    public static implicit operator VertexIndex(uint value) => new VertexIndex(value);
    public static implicit operator uint(VertexIndex index) => index.Value;
    public static implicit operator int(VertexIndex index) => (int)index.Value;

    public override string ToString() => Value.ToString();
}

/// <summary>
/// Edge index type (equivalent to u32 or usize in Rust)
/// </summary>
public readonly struct EdgeIndex
{
    public readonly uint Value;

    public EdgeIndex(uint value)
    {
        Value = value;
    }

    public static implicit operator EdgeIndex(uint value) => new EdgeIndex(value);
    public static implicit operator uint(EdgeIndex index) => index.Value;
    public static implicit operator int(EdgeIndex index) => (int)index.Value;

    public override string ToString() => Value.ToString();
}

// Type aliases
// using VertexNum = System.UInt32;
// using NodeIndex = VertexIndex;
// using DefectIndex = VertexIndex;
