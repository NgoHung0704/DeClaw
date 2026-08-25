import ownershipJson from '../../content/ownership.json';
import { componentById, ui } from '../content/load';
import type { Store } from '../content/types';
import { githubUrl } from '../content/links';
import { useT } from '../i18n/lang';

const stores = (ownershipJson as unknown as { stores: Store[] }).stores;

export function OwnershipTable() {
  const t = useT();
  const nameOf = (id: string) => {
    const component = componentById.get(id);
    return component ? t(component.title) : id;
  };

  return (
    <section className="ownership" id="ownership">
      <h2>{t(ui.map.ownershipHeading)}</h2>
      <p className="lede">{t(ui.map.ownershipIntro)}</p>
      <div className="table-scroll">
        <table className="ownership__table">
          <thead>
            <tr>
              <th scope="col">{t(ui.map.colStore)}</th>
              <th scope="col">{t(ui.map.colKind)}</th>
              <th scope="col">{t(ui.map.colOwner)}</th>
              <th scope="col">{t(ui.map.colWriters)}</th>
              <th scope="col">{t(ui.map.colReaders)}</th>
              <th scope="col">{t(ui.map.colLifetime)}</th>
            </tr>
          </thead>
          <tbody>
            {stores.map((store) => (
              <tr key={store.id}>
                <th scope="row">
                  <a
                    className="link"
                    href={githubUrl(store.enforcement.file, store.enforcement.start, store.enforcement.end)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t(store.label)}
                  </a>
                </th>
                <td>{t(store.kind)}</td>
                <td>{nameOf(store.owner)}</td>
                <td>{store.writers.map(nameOf).join(', ')}</td>
                <td>{store.readers.map(nameOf).join(', ')}</td>
                <td>{t(store.lifetime)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="ownership__notes">
        {stores.map((store) => (
          <li key={store.id}>
            <strong>{t(store.label)}</strong>
            <span>{t(store.enforcement.note)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
