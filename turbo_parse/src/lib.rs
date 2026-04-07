use pyo3::prelude::*;

#[pymodule]
fn turbo_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
